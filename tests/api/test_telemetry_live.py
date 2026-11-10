import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from weeing_weeing.api import telemetry, telemetry_live
from weeing_weeing.api.app import app
from weeing_weeing.contracts import Role, TelemetryRecord, UserAccount
from weeing_weeing.db import interface as db
from weeing_weeing.detector.interface import HistoryReader

FAKE_TOKEN = "fake-producer-token-for-tests-only"


@pytest.fixture
def live_client(tmp_path, monkeypatch):

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db.sqlite'}")
    monkeypatch.setenv("TELEMETRY_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setenv("TELEMETRY_DB_ENABLED", "true")
    monkeypatch.setenv("ANALYSIS_AUTO_ENABLED", "false")
    monkeypatch.setenv("TELEMETRY_AUTH_REQUIRED", "true")
    monkeypatch.setenv(
        "TELEMETRY_PRODUCER_TOKEN_SHA256",
        hashlib.sha256(FAKE_TOKEN.encode()).hexdigest(),
    )
    monkeypatch.setattr(telemetry_live, "live_state", telemetry_live.LiveTelemetry())
    db.get_users().create_user(
        UserAccount(employee_no="A0001", name="테스트", role=Role.CONTROL),
        "fake-password-for-tests",
    )
    with TestClient(app) as client:
        response = client.post(
            "/auth/login",
            json={
                "employee_no": "A0001",
                "password": "fake-password-for-tests",
            },
        )
        yield client, {"Authorization": f"Bearer {response.json()['access_token']}"}


def row(sample_rows):
    return TelemetryRecord.model_validate(sample_rows[0]).model_dump(mode="json")


@pytest.mark.parametrize(
    "change",
    [
        {"telemetry_simulation_rpm_enabled": False},
        {"telemetry_auth_required": True},
        {"telemetry_producer_token_sha256": " " + "a" * 64},
        {"analysis_auto_enabled": True},
        {"peer": "192.0.2.20"},
        {"host": "public.example"},
        {"peer": None},
    ],
)
def test_simulation_rpm_is_local_opt_in_only(change):
    options = {
        "telemetry_simulation_rpm_enabled": True,
        "telemetry_auth_required": False,
        "telemetry_producer_token_sha256": "",
        "analysis_auto_enabled": False,
        "peer": "127.0.0.1",
        "host": "127.0.0.1",
    }

    def allowed(values):
        values = dict(values)
        peer = values.pop("peer")
        host = values.pop("host")
        return telemetry._simulation_rpm_allowed(
            SimpleNamespace(
                client=None if peer is None else SimpleNamespace(host=peer),
                url=SimpleNamespace(hostname=host),
            ),
            SimpleNamespace(**values),
        )

    assert allowed(options)
    assert not allowed({**options, **change})
    assert allowed({**options, "peer": "::1", "host": "::1"})


def test_simulation_rpm_rejected_before_history_and_producer(live_client, tmp_path):
    client, _ = live_client
    with client.websocket_connect(
        "/ws/telemetry?context=SIM_RPM",
        headers={"Authorization": f"Bearer {FAKE_TOKEN}"},
    ) as ws:
        assert ws.receive_json()["code"] == "simulation_context_disabled"
    assert not (tmp_path / "history").exists()
    assert not telemetry._producer.locked()


@pytest.mark.parametrize("context", ["NONE", "RUN_ONLY", "MINIMAL", "SIM_RPM"])
def test_rpm_simulation_alarm_lifecycle_and_legacy_contexts(
    live_client, monkeypatch, sample_rows, context
):
    _, headers = live_client
    monkeypatch.setenv("TELEMETRY_SIMULATION_RPM_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_AUTH_REQUIRED", "false")
    monkeypatch.setenv("TELEMETRY_PRODUCER_TOKEN_SHA256", "")
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    original = row(sample_rows)
    start = datetime.fromisoformat(original["timestamp"])
    changes = []
    with client.websocket_connect(
        f"ws://127.0.0.1/ws/telemetry?context={context}"
    ) as ws:
        ready = ws.receive_json()
        assert ready["context_preset"] == context
        for index in range(59):
            seconds = index / 2
            rpm = (
                1015 if seconds < 5 or seconds >= 17 else 1035 if seconds < 11 else 1045
            )
            ws.send_json(
                {
                    **original,
                    "record_id": f"sim-{context}-{index}",
                    "timestamp": (start + timedelta(seconds=seconds)).isoformat(),
                    "rpm": rpm,
                    "infeed_present": False,
                    "outfeed_present": False,
                }
            )
            ack = ws.receive_json()
            assert ack["status"] == "processed"
            assert ack["db_status"] == "saved"
            assert ack["agent_status"] == "not_connected"
            assert ack["analysis_jobs"] == []
            changes.extend(
                item for item in ack["incidents"] if "BTT2-M03" in item["codes"]
            )
        state = client.get("/telemetry/latest", headers=headers).json()
        assert state["context_preset"] == context
        assert state["telemetry"]["rpm"] == 1015
    if context != "SIM_RPM":
        assert changes == []  # Merely opting in never alters legacy contexts.
        return
    lifecycle = []
    for item in changes:
        stage = (item["severity"], item["status"])
        if not lifecycle or lifecycle[-1] != stage:
            lifecycle.append(stage)
    assert lifecycle == [
        ("Warning", "OPEN"),
        ("Error", "OPEN"),
        ("Error", "RECOVERED"),
    ]
    assert len({item["incident_id"] for item in changes}) == 1
    incident_id = changes[0]["incident_id"]
    persisted = next(
        item
        for item in client.get("/incidents", headers=headers).json()
        if item["incident_id"] == incident_id
    )
    assert persisted["status"] == "RECOVERED"
    assert persisted["severity"] == "Error"
    assert persisted["recovered_at"] is not None
    reader = HistoryReader(ready["run_path"])
    assert reader.validate()
    assert "LOCAL TEST ONLY" in reader.manifest["source"]["assumptions"]
    # A reconnect starts its own startup grace and persistence timer.
    with client.websocket_connect("ws://127.0.0.1/ws/telemetry?context=SIM_RPM") as ws:
        assert ws.receive_json()["run_id"] != ready["run_id"]
        for index in range(13):
            ws.send_json(
                {
                    **original,
                    "record_id": f"restart-{index}",
                    "timestamp": (
                        start + timedelta(seconds=60 + index / 2)
                    ).isoformat(),
                    "rpm": 1045,
                }
            )
            incidents = ws.receive_json()["incidents"]
            m03 = [item for item in incidents if "BTT2-M03" in item["codes"]]
            if index < 12:
                assert m03 == []
            else:
                assert m03[0]["severity"] == "Error"


def test_stream_disables_proxy_transformation():
    response = telemetry_live.stream_telemetry(None, None, None)
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-store, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


def test_auth_denied_before_producer_and_history(live_client, tmp_path):
    client, headers = live_client
    for auth in ({}, {"Authorization": "Bearer wrong"}):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/telemetry", headers=auth):
                pass
    assert not (tmp_path / "history").exists()
    assert not telemetry._producer.locked()
    assert client.get("/telemetry/latest").status_code == 401
    assert client.get("/telemetry/stream").status_code == 401
    snapshot = client.get("/telemetry/latest", headers=headers)
    assert snapshot.json()["stale"]
    assert snapshot.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("digest", ["", "malformed", "x" * 64])
def test_required_auth_fails_closed_without_valid_hash(
    live_client, monkeypatch, digest
):
    client, _ = live_client
    monkeypatch.setenv("TELEMETRY_PRODUCER_TOKEN_SHA256", digest)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws/telemetry", headers={"Authorization": f"Bearer {FAKE_TOKEN}"}
        ):
            pass
    assert not telemetry._producer.locked()


def test_six_viewers_share_saved_frame_and_disconnect_is_not_recovery(
    live_client, sample_rows
):
    client, headers = live_client
    payload = row(sample_rows)
    with client.websocket_connect(
        "/ws/telemetry?context=RUN_ONLY",
        headers={"Authorization": f"Bearer {FAKE_TOKEN}"},
    ) as ws:
        run = ws.receive_json()["run_id"]
        ws.send_json(payload)
        assert ws.receive_json()["db_status"] == "saved"
        states = [
            client.get("/telemetry/latest", headers=headers).json() for _ in range(6)
        ]
        assert {s["run_id"] for s in states} == {run}
        assert len({s["sequence"] for s in states}) == 1
        assert all(s["telemetry"] == payload and not s["stale"] for s in states)
        stored = db.get_telemetry().latest(
            payload["asset_id"], process_id=payload["process_id"]
        )
        assert stored.record_id == payload["record_id"]
        with client.websocket_connect(
            "/ws/telemetry", headers={"Authorization": f"Bearer {FAKE_TOKEN}"}
        ) as second:
            assert second.receive_json()["code"] == "producer_busy"
    state = client.get("/telemetry/latest", headers=headers).json()
    assert state["stale"] and not state["producer_connected"]
    assert state["telemetry"] == payload
    assert state["incidents"] == states[0]["incidents"]
    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/telemetry/latest", headers=headers).status_code == 401


def test_db_failure_is_visible_without_replay(live_client, sample_rows, monkeypatch):
    client, headers = live_client
    with client.websocket_connect(
        "/ws/telemetry", headers={"Authorization": f"Bearer {FAKE_TOKEN}"}
    ) as ws:
        ws.receive_json()
        monkeypatch.setattr(
            app.state.analysis_service,
            "repository",
            lambda: SimpleNamespace(
                record_frame=lambda *args, **kwargs: (_ for _ in ()).throw(
                    db.DatabaseUnavailableError("fake failure")
                )
            ),
        )
        ws.send_json(row(sample_rows))
        assert ws.receive_json()["db_status"] == "failed"
        state = client.get("/telemetry/latest", headers=headers).json()
        assert state["db_status"] == "failed"
        assert state["agent_status"] == "storage_failed"


def test_idle_producer_releases_slot(live_client, monkeypatch):
    client, _ = live_client
    monkeypatch.setattr(telemetry, "PRODUCER_IDLE_SECONDS", 0.05)
    with client.websocket_connect(
        "/ws/telemetry", headers={"Authorization": f"Bearer {FAKE_TOKEN}"}
    ) as ws:
        ws.receive_json()
        assert ws.receive_json()["code"] == "producer_idle"
    assert not telemetry._producer.locked()


def test_sse_six_consumers_and_revoked_session(monkeypatch):
    state = telemetry_live.LiveTelemetry()
    state.start("run-test", "NONE")
    monkeypatch.setattr(telemetry_live, "live_state", state)

    async def exercise():
        readers = [
            telemetry_live.telemetry_events(lambda: None, interval=0) for _ in range(6)
        ]
        try:
            frames = await asyncio.gather(*(anext(reader) for reader in readers))
            assert len(set(frames)) == 1
            state.end("run-test")
            latest = await anext(readers[0])
            assert not json.loads(latest.split("data: ", 1)[1])["state"][
                "producer_connected"
            ]
            # A slow reader has no queue; its next read sees the latest state.
            assert "false" in await anext(readers[5])
        finally:
            for reader in readers:
                await reader.aclose()

        checks = 0

        def revoked():
            nonlocal checks
            checks += 1
            if checks > 1:
                raise HTTPException(401, "revoked")

        reader = telemetry_live.telemetry_events(revoked, interval=0, auth_interval=0)
        assert "event: snapshot" in await anext(reader)
        assert '"status_code": 401' in await anext(reader)
        with pytest.raises(StopAsyncIteration):
            await anext(reader)

    asyncio.run(exercise())


def test_new_run_clears_live_cache_but_not_persisted_incidents(
    monkeypatch, sample_rows
):
    state = telemetry_live.LiveTelemetry()
    monkeypatch.setattr(telemetry_live.time, "monotonic", lambda: 10)
    state.start("a", "RUN_ONLY")
    state.publish(
        "a",
        TelemetryRecord.model_validate(sample_rows[0]),
        {"incidents": [], "db_status": "saved"},
    )
    monkeypatch.setattr(telemetry_live.time, "monotonic", lambda: 14)
    assert state.snapshot()["stale"]
    state.start("b", "NONE")
    state.end("a")
    assert state.snapshot()["producer_connected"]
    assert state.snapshot()["telemetry"] is None
