import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from weeing_weeing.api import telemetry
from weeing_weeing.api.app import app
from weeing_weeing.contracts import TelemetryRecord
from weeing_weeing.detector.interface import HistoryReader, RuleDetector
from weeing_weeing.ingest.interface import CsvJsonSource


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEMETRY_HISTORY_DIR", str(tmp_path / "history"))
    with TestClient(app) as client:
        yield client


def payload(sample_rows, index=0):
    record = TelemetryRecord.model_validate(sample_rows[0]).model_dump(mode="json")
    record["record_id"] = f"ws-{index}"
    record["timestamp"] = (
        datetime.fromisoformat(record["timestamp"]) + timedelta(seconds=index / 2)
    ).isoformat()
    return record


@pytest.mark.parametrize(
    "query", ["origin=guess", "interval_s=-1", "interval_s=nan", "interval_s=100"]
)
def test_invalid_source_metadata_is_rejected_before_allocating_producer(client, query):
    with client.websocket_connect(f"/ws/telemetry?{query}") as ws:
        assert ws.receive_json() == {"status": "rejected", "code": "invalid_provenance"}
    with client.websocket_connect("/ws/telemetry") as ws:
        assert ws.receive_json()["status"] == "connected"


def test_server_console_logs_all_fields_only_after_success(client, sample_rows, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.telemetry")
    row = payload(sample_rows)
    with client.websocket_connect("/ws/telemetry") as ws:
        ws.receive_json()
        ws.send_text('{"secret":"unvalidated-value"}')
        assert ws.receive_json()["status"] == "rejected"
        ws.send_json(row)
        assert ws.receive_json()["status"] == "processed"
        # A conflicting ID fails in history, not in the JSON parser. It must
        # never produce a successful sensor log containing its changed value.
        ws.send_json({**payload(sample_rows, 1), "record_id": "ws-0", "rpm": 1234567})
        assert ws.receive_json()["status"] == "failed"
    messages = [r.getMessage() for r in caplog.records]
    processed = [m for m in messages if m.startswith("[센서 처리")]
    assert len(processed) == 1
    assert "#0001" in processed[0] and "processed_at=" in processed[0]
    data = json.loads(processed[0].split(" data=", 1)[1])
    assert data == TelemetryRecord.model_validate(row).model_dump(mode="json")
    assert len(data) == 15
    assert any("[센서 거부]" in m for m in messages)
    assert "unvalidated-value" not in "\n".join(messages)
    assert "1234567" not in "\n".join(messages)


def test_normal_bytes_and_invalid_then_valid(client, sample_rows):
    with client.websocket_connect("/ws/telemetry") as ws:
        ready = ws.receive_json()
        assert ready["status"] == "connected"
        assert ready["context_preset"] == "NONE"
        for message in ("{", "[]", b"\xff", " " * 65537):
            if isinstance(message, bytes):
                ws.send_bytes(message)
            else:
                ws.send_text(message)
            assert ws.receive_json() == {
                "status": "rejected",
                "code": "invalid_telemetry",
            }
        ws.send_bytes(json.dumps(payload(sample_rows)).encode())
        result = ws.receive_json()
        assert result["status"] == "processed"
        assert result["record_id"] == "ws-0"
        assert result["agent_status"] == "not_connected"
        assert result["error_entries"] == []
    reader = HistoryReader(ready["run_path"])
    assert reader.validate()
    assert reader.manifest["accepted_records"] == 1
    assert reader.manifest["source"]["context_preset"] == "NONE"


def test_duplicate_and_asset_rejection_do_not_evaluate_twice(client, sample_rows):
    with client.websocket_connect("/ws/telemetry") as ws:
        ready = ws.receive_json()
        row = payload(sample_rows)
        ws.send_json(row)
        ws.receive_json()
        ws.send_json(row)
        assert ws.receive_json()["incidents"] == []
        ws.send_json({**payload(sample_rows, 1), "asset_id": "other"})
        assert ws.receive_json()["status"] == "rejected"
        ws.send_json(payload(sample_rows, 1))
        assert ws.receive_json()["status"] == "processed"
    reader = HistoryReader(ready["run_path"])
    assert reader.validate()
    assert reader.manifest["accepted_records"] == 2


def test_invalid_context_and_single_producer(client):
    with client.websocket_connect("/ws/telemetry?context=UNKNOWN") as ws:
        assert ws.receive_json()["code"] == "invalid_context"
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1008
    with client.websocket_connect("/ws/telemetry") as first:
        first.receive_json()
        with client.websocket_connect("/ws/telemetry") as second:
            assert second.receive_json()["code"] == "producer_busy"
    # Disconnect releases the slot. Reconnect is a new history run.
    with client.websocket_connect("/ws/telemetry") as ws:
        assert ws.receive_json()["status"] == "connected"


def test_failure_closes_poisoned_history_and_releases_slot(client, sample_rows):
    with client.websocket_connect("/ws/telemetry") as ws:
        ready = ws.receive_json()
        ws.send_json(payload(sample_rows))
        ws.receive_json()
        ws.send_json({**payload(sample_rows, 1), "record_id": "ws-0"})
        assert ws.receive_json() == {"status": "failed", "code": "processing_failed"}
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1011
    manifest = json.loads(
        (Path(ready["run_path"]) / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "failed"
    with client.websocket_connect("/ws/telemetry") as ws:
        assert ws.receive_json()["run_id"] != ready["run_id"]


def test_parser_keeps_duplicate_keys_and_type_checks(client, sample_rows):
    row = payload(sample_rows)
    with client.websocket_connect("/ws/telemetry") as ws:
        ws.receive_json()
        for message in (
            json.dumps(row)[:-1] + ', "record_id":"secret"}',
            json.dumps({**row, "rpm": "1015"}),
            json.dumps({k: v for k, v in row.items() if k != "dc_input_current_a"}),
        ):
            ws.send_text(message)
            reply = ws.receive_json()
            assert reply["status"] == "rejected"
            assert "secret" not in json.dumps(reply)


def test_half_second_error_entry_once_and_recovery_not_dispatched(client, sample_rows):
    entries = []
    direct = RuleDetector()
    with client.websocket_connect("/ws/telemetry?context=RUN_ONLY") as ws:
        ready = ws.receive_json()
        for tick in range(70):
            row = {
                **payload(sample_rows, tick),
                "motor_housing_temp_c": 88 if tick < 24 else 95 if tick < 46 else 65,
            }
            expected = direct.process(
                TelemetryRecord.model_validate(row), {"run_cmd": True}
            )
            ws.send_json(row)
            result = ws.receive_json()
            assert [
                {k: v for k, v in i.items() if k != "incident_id"}
                for i in result["incidents"]
            ] == [i.model_dump(mode="json", exclude={"incident_id"}) for i in expected]
            entries.extend(result["error_entries"])
    m10_entries = [i for i in entries if i["codes"] == ["BTT2-M10"]]
    assert len(m10_entries) == 1
    assert m10_entries[0]["status"] == "OPEN"
    reader = HistoryReader(ready["run_path"])
    assert reader.validate()
    m10 = next(
        i for i in reader.list_incidents() if reader.incident(i).codes == ["BTT2-M10"]
    )
    assert reader.incident(m10).status == "RECOVERED"


def test_v4_websocket_history_and_error_entries(client):
    path = (
        Path(__file__).resolve().parents[2]
        / "data/telemetry/battery_tray_transfer_5min_warning_error_v4.csv"
    )
    if not path.is_file():
        pytest.skip("Actual v4 CSV not available")
    entries, changes, rows = [], 0, 0
    with client.websocket_connect("/ws/telemetry?context=MINIMAL") as ws:
        ready = ws.receive_json()
        for message in CsvJsonSource(path):
            ws.send_text(message)
            result = ws.receive_json()
            assert result["status"] == "processed"
            changes += len(result["incidents"])
            entries.extend(result["error_entries"])
            rows += 1
    assert rows == 300
    assert changes == 372
    assert sorted(i["codes"] for i in entries) == [["BTT2-M08"], ["BTT2-M10"]]
    reader = HistoryReader(ready["run_path"])
    assert reader.validate()
    assert len(reader.list_incidents()) == 3


def test_storage_failure_is_not_acked_or_retried(client, sample_rows, monkeypatch):
    calls = []
    original = telemetry.HistoryDetector.process

    def fail_save(self):
        raise OSError("secret disk error")

    def process(self, *args, **kwargs):
        calls.append(1)
        monkeypatch.setattr(self, "_save_manifest", fail_save.__get__(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(telemetry.HistoryDetector, "process", process)
    with client.websocket_connect("/ws/telemetry") as ws:
        ready = ws.receive_json()
        ws.send_json(payload(sample_rows))
        assert ws.receive_json() == {"status": "failed", "code": "processing_failed"}
    assert calls == [1]
    # Previous durable running manifest remains visibly incomplete when even the
    # failed-state write cannot be saved.
    manifest = json.loads(
        (Path(ready["run_path"]) / "manifest.json").read_text(encoding="utf-8")
    )
    assert not manifest["completed"]


@pytest.mark.parametrize("phase", ["create", "receive", "close"])
def test_route_cancellation_finishes_worker_before_close_and_release(
    phase, tmp_path, monkeypatch
):
    """Explicit asyncio cancellation must not race thread writes and cleanup."""
    started = Event()
    unblock = Event()
    steps = []

    def operation(name):
        steps.append(f"{name}_started")
        if name == phase:
            started.set()
            assert unblock.wait(timeout=5), "Test worker wasn't released"
        steps.append(f"{name}_finished")

    class Session:
        def __init__(self, *args):
            operation("create")
            self.history = SimpleNamespace(run_path=tmp_path)
            self.processed_count = 0
            self.failed = False

        def receive(self, message):
            operation("receive")
            return {"status": "processed"}

        def close(self):
            operation("close")

    class Producer:
        def __init__(self):
            self.lock = Lock()

        def acquire(self, **kwargs):
            return self.lock.acquire(**kwargs)

        def release(self):
            steps.append("released")
            self.lock.release()

    class Socket:
        async def accept(self):
            pass

        async def send_json(self, message):
            pass

        async def close(self, **kwargs):
            pass

        async def receive(self):
            if phase == "close":
                return {"type": "websocket.disconnect"}
            return {"type": "websocket.receive", "text": "{}"}

    producer = Producer()
    monkeypatch.setattr(telemetry, "TelemetrySession", Session)
    monkeypatch.setattr(telemetry, "_producer", producer)

    async def exercise():
        task = asyncio.create_task(telemetry.telemetry_socket(Socket()))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            task.cancel()
            # Give the cancellation handler time to run while the worker remains
            # explicitly blocked. A second cancellation also must not release it.
            await asyncio.sleep(0.02)
            task.cancel()
            await asyncio.sleep(0.02)
            assert producer.lock.locked()
            assert "close_finished" not in steps
            if phase != "close":
                assert "close_started" not in steps
        finally:
            unblock.set()
            try:
                await asyncio.wait_for(task, timeout=3)
            except asyncio.CancelledError:
                pass
        assert steps.index("create_finished") < steps.index("close_started")
        if phase == "receive":
            assert steps.index("receive_finished") < steps.index("close_started")
        assert steps.index("close_finished") < steps.index("released")
        assert steps.count("close_started") == 1
        assert steps.count("released") == 1
        assert not producer.lock.locked()

    asyncio.run(exercise())
