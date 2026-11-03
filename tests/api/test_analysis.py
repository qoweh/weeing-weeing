"""가짜 Analyzer와 실제 SQLite로 수신과 분석 분리·조회·권한을 검증한다."""

import time
from datetime import UTC, datetime
from threading import Event, Thread
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from weeing_weeing.api.analysis import AnalysisService
from weeing_weeing.api.app import app
from weeing_weeing.api.auth import current_user
from weeing_weeing.contracts import (
    AnalysisResult,
    Incident,
    Role,
    TelemetryRecord,
    UserAccount,
)
from weeing_weeing.db import interface as db


@pytest.fixture
def setup(tmp_path, sample_rows, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    repo = db.open_analysis_jobs(database_url)
    frame = TelemetryRecord.model_validate(sample_rows[0])
    item = Incident(
        incident_id="INC-api-test",
        process_id=frame.process_id,
        asset_id=frame.asset_id,
        codes=["BTT2-P03"],
        severity="Error",
        first_detected_at=frame.timestamp,
        last_detected_at=frame.timestamp,
    )
    monkeypatch.setattr(db, "get_analysis_jobs", lambda: repo)
    monkeypatch.setenv("ANALYSIS_AUTO_ENABLED", "false")
    monkeypatch.setenv("TELEMETRY_HISTORY_DIR", str(tmp_path / "history"))
    yield repo, frame, item
    app.dependency_overrides.clear()
    repo._engine.dispose()


def test_blocked_analyzer_does_not_block_websocket(setup):
    repo, frame, item = setup
    started, release = Event(), Event()

    class Fake:
        def analyze(self, snapshot):
            started.set()
            assert release.wait(5)
            return AnalysisResult(
                incident_id=snapshot.incident_id,
                status="INSUFFICIENT_EVIDENCE",
                observed_facts="fake",
                model="fake/no-api",
                generated_at=datetime.now(UTC),
            )

    service = AnalysisService(lambda: repo, lambda: Fake())
    service.ingest(frame, [item])
    worker = Thread(target=service.process_one)
    worker.start()
    assert started.wait(2)
    try:
        with TestClient(app) as client:
            app.state.analysis_service = service
            with client.websocket_connect("/ws/telemetry") as ws:
                assert ws.receive_json()["agent_status"] == "connected"
                ws.send_json(frame.model_dump(mode="json"))
                response = ws.receive_json()
                assert response["status"] == "processed"
                assert response["db_status"] == "saved"
                assert repo.latest_job(item.incident_id)["status"] == "RUNNING"
    finally:
        release.set()
        worker.join(5)
    assert repo.latest_job(item.incident_id)["status"] == "COMPLETED"


def test_storage_error_does_not_escape_into_detector(setup, caplog):
    repo, frame, item = setup

    def fail():
        raise db.DatabaseUnavailableError("SECRET must not be logged")

    service = AnalysisService(fail)
    assert service.ingest(frame, [item])["agent_status"] == "storage_failed"
    assert "SECRET" not in caplog.text


def test_analyzer_exception_is_failed_without_retry(setup, caplog):
    repo, frame, item = setup

    def bad_factory():
        raise RuntimeError("SECRET provider failure")

    service = AnalysisService(lambda: repo, bad_factory)
    service.ingest(frame, [item])
    assert service.process_one()
    assert not service.process_one()
    assert repo.latest_job(item.incident_id)["status"] == "FAILED"
    assert "SECRET" not in caplog.text


def test_query_and_manual_retry_auth_and_idempotency(setup):
    repo, frame, item = setup
    service = AnalysisService(lambda: repo)
    service.ingest(frame, [item])
    job_id, _ = repo.claim()
    repo.fail(job_id, "test_failure")
    path = f"/incidents/{item.incident_id}/analysis"
    with TestClient(app) as client:
        app.state.analysis_service = service
        assert client.get(path).status_code == 401
        user = UserAccount(employee_no="TEST01", name="test", role=Role.INSPECTOR)
        app.dependency_overrides[current_user] = lambda: user
        assert client.get(path).json()["job"]["status"] == "FAILED"
        request = {"request_id": str(uuid4())}
        assert client.post(path + "/retry", json=request).status_code == 403
        user = user.model_copy(update={"role": Role.CONTROL})
        first = client.post(path + "/retry", json=request)
        assert first.status_code == 202
        assert client.post(path + "/retry", json=request).json() == first.json()
        assert client.get("/incidents/not-found/analysis").status_code == 404


def test_result_save_retry_never_repeats_llm(setup, monkeypatch):
    repo, frame, item = setup
    calls = []

    class Fake:
        def analyze(self, snapshot):
            calls.append(snapshot.incident_id)
            return AnalysisResult(
                incident_id=snapshot.incident_id,
                status="INSUFFICIENT_EVIDENCE",
                observed_facts="fake",
                model="fake/no-api",
                generated_at=datetime.now(UTC),
            )

    original = repo.finish

    def offline(*args):
        raise db.DatabaseUnavailableError("offline")

    service = AnalysisService(lambda: repo, lambda: Fake())
    service.ingest(frame, [item])
    monkeypatch.setattr(repo, "finish", offline)
    with pytest.raises(db.DatabaseUnavailableError):
        service.process_one()
    monkeypatch.setattr(repo, "finish", original)
    assert service.process_one()
    assert calls == [item.incident_id]
    assert repo.latest_job(item.incident_id)["status"] == "COMPLETED"


def test_commit_success_with_lost_response_does_not_stall_worker(setup, monkeypatch):
    repo, frame, item = setup
    calls = []

    class Fake:
        def analyze(self, snapshot):
            calls.append(snapshot.incident_id)
            return AnalysisResult(
                incident_id=snapshot.incident_id,
                status="INSUFFICIENT_EVIDENCE",
                observed_facts="fake",
                model="fake/no-api",
                generated_at=datetime.now(UTC),
            )

    original = repo.finish

    def lost_reply(*args):
        original(*args)
        raise db.DatabaseUnavailableError("commit reply lost")

    service = AnalysisService(lambda: repo, lambda: Fake())
    service.ingest(frame, [item])
    monkeypatch.setattr(repo, "finish", lost_reply)
    with pytest.raises(db.DatabaseUnavailableError):
        service.process_one()
    monkeypatch.setattr(repo, "finish", original)
    assert service.process_one()
    assert service.pending_result is None
    assert len(repo.list_analyses(item.incident_id)) == 1
    next_item = item.model_copy(update={"incident_id": "INC-next"})
    service.ingest(frame, [next_item])
    assert service.process_one()
    assert calls == [item.incident_id, next_item.incident_id]


def test_claim_commit_lost_reply_recovers_without_paid_retry(setup, monkeypatch):
    repo, frame, item = setup
    calls = []
    original = repo.claim
    lost_once = False

    def claim():
        nonlocal lost_once
        work = original()
        if work and not lost_once:
            lost_once = True
            raise db.DatabaseUnavailableError("claim reply lost")
        return work

    class Fake:
        def analyze(self, snapshot):
            calls.append(snapshot.incident_id)
            return AnalysisResult(
                incident_id=snapshot.incident_id,
                status="INSUFFICIENT_EVIDENCE",
                observed_facts="fake",
                model="fake/no-api",
                generated_at=datetime.now(UTC),
            )

    monkeypatch.setattr(repo, "claim", claim)
    service = AnalysisService(lambda: repo, lambda: Fake(), poll_seconds=0.01)
    service.ingest(frame, [item])
    service.start()
    try:
        deadline = time.monotonic() + 3
        while repo.latest_job(item.incident_id)["status"] != "FAILED":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert repo.latest_job(item.incident_id)["error_code"] == "interrupted"
        assert calls == []
        next_item = item.model_copy(update={"incident_id": "INC-after-lost-claim"})
        service.ingest(frame, [next_item])
        while repo.latest_job(next_item.incident_id)["status"] != "COMPLETED":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert calls == [next_item.incident_id]
    finally:
        service.stop()
