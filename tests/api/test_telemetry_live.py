import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from weeing_weeing.api import telemetry, telemetry_live
from weeing_weeing.api.app import app
from weeing_weeing.contracts import Role, TelemetryRecord, UserAccount
from weeing_weeing.db import interface as db

FAKE_TOKEN = "fake-producer-token-for-tests-only"


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    from weeing_weeing.db import users

    monkeypatch.setattr(users, "SCRYPT_N", 2**10)
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
