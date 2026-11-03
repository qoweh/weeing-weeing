"""Real TCP/Uvicorn tests for the CSV sender (no external server required)."""

import csv
import json
import os
import runpy
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn

from weeing_weeing.api.app import app
from weeing_weeing.detector.interface import HistoryReader

ROOT = Path(__file__).resolve().parents[2]
send_csv = runpy.run_path(str(ROOT / "scripts/send_csv_websocket.py"))["send_csv"]


@pytest.fixture
def server(tmp_path, monkeypatch):
    output = tmp_path / "history"
    monkeypatch.setenv("TELEMETRY_HISTORY_DIR", str(output))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, log_level="error", ws_max_size=65536, ws_max_queue=4)
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                pytest.fail("Local Uvicorn didn't start")
            time.sleep(0.01)
        yield f"ws://127.0.0.1:{port}/ws/telemetry", output
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def finalized(output):
    # The last ACK confirms row persistence; connection-close finalization happens
    # afterwards. Wait for that before running the existing integrity reader.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        manifests = list(output.glob("run-*/manifest.json"))
        if manifests:
            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
            if manifest["status"] != "running":
                return manifests[0].parent, manifest
        time.sleep(0.01)
    pytest.fail("History didn't finalize")


def test_sender_real_network_keeps_records(server, tmp_path, sample_rows, capsys):
    url, output = server
    with urllib.request.urlopen(
        url.replace("ws://", "http://").replace("/ws/telemetry", "/health"),
        timeout=3,
    ) as response:
        assert json.load(response)["status"] == "ok"
    csv_path = tmp_path / "source.csv"
    write_csv(csv_path, sample_rows[:4])
    assert send_csv(csv_path, url, interval=0.01, timeout=3) == 4
    captured = capsys.readouterr().out
    assert captured.count("[처리 #") == 4
    assert sample_rows[0]["timestamp"] in captured
    assert "Agent 미연결" not in captured  # no Error in this short run
    run_path, manifest = finalized(output)
    assert manifest["accepted_records"] == 4
    assert HistoryReader(run_path).validate()


def test_sender_stops_on_failed_ack_without_retry(
    server, tmp_path, sample_rows, capsys
):
    url, output = server
    csv_path = tmp_path / "bad_order.csv"
    rows = [
        sample_rows[0],
        {**sample_rows[1], "record_id": sample_rows[0]["record_id"]},
        sample_rows[2],
    ]
    write_csv(csv_path, rows)
    with pytest.raises(RuntimeError, match="replay stopped"):
        send_csv(csv_path, url, interval=0, timeout=3)
    assert capsys.readouterr().out.count("[처리 #") == 1
    _, manifest = finalized(output)
    assert manifest["status"] == "failed"
    assert manifest["accepted_records"] == 1


def test_v4_cli_over_real_websocket(server):
    url, output = server
    csv_path = ROOT / "data/telemetry/battery_tray_transfer_5min_warning_error_v4.csv"
    if not csv_path.is_file():
        pytest.skip("Actual v4 CSV not available")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/send_csv_websocket.py"),
            "--csv",
            str(csv_path),
            "--url",
            url,
            "--context",
            "MINIMAL",
            "--interval",
            "0",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("[처리 #") == 300
    assert result.stdout.count("[Error 진입]") == 2
    assert "[송신 완료] 300행" in result.stdout
    run_path, manifest = finalized(output)
    reader = HistoryReader(run_path)
    assert reader.validate()
    assert manifest["accepted_records"] == 300
    ids = reader.list_incidents()
    assert len(ids) == 3
    assert sum(sum(1 for _ in reader.events(i)) for i in ids) == 372


@pytest.mark.parametrize(
    "kwargs", [{"interval": -1}, {"timeout": 0}, {"timeout": float("nan")}]
)
def test_sender_rejects_invalid_settings_before_connect(tmp_path, kwargs):
    with pytest.raises(ValueError):
        send_csv(tmp_path / "missing.csv", "ws://127.0.0.1:1/ws/telemetry", **kwargs)
