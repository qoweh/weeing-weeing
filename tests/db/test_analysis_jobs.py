"""실제 DB에서 원자성·중복·스냅샷·재시도·중단 복구를 확인한다."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from weeing_weeing.contracts import (
    AnalysisResult,
    Incident,
    IncidentStatus,
    Severity,
    TelemetryRecord,
)
from weeing_weeing.db import interface as db
from weeing_weeing.db.models import AnalysisJobRow, AnalysisRow


@pytest.fixture
def jobs(database_url):
    repo = db.open_analysis_jobs(database_url)
    yield repo
    repo._engine.dispose()


@pytest.fixture
def frame(sample_rows):
    return TelemetryRecord.model_validate(sample_rows[0])


def incident(frame, **overrides):
    return Incident(
        **{
            "incident_id": "INC-job-test",
            "process_id": frame.process_id,
            "asset_id": frame.asset_id,
            "codes": ["BTT2-P03"],
            "severity": Severity.ERROR,
            "first_detected_at": frame.timestamp,
            "last_detected_at": frame.timestamp,
            **overrides,
        }
    )


def result(item, status="INSUFFICIENT_EVIDENCE"):
    return AnalysisResult(
        incident_id=item.incident_id,
        status=status,
        observed_facts="센서 확인 필요",
        model="fake/no-api",
        generated_at=item.last_detected_at,
    )


def test_warning_error_repeated_recovered_and_snapshot(jobs, frame):
    warning = incident(frame, severity=Severity.WARNING)
    assert jobs.record_frame(frame, [warning]) == []
    error = incident(frame)
    first = jobs.record_frame(frame, [error])[0]
    assert jobs.record_frame(frame, [error])[0]["job_id"] == first["job_id"]
    recovered = error.model_copy(
        update={
            "status": IncidentStatus.RECOVERED,
            "last_detected_at": error.last_detected_at + timedelta(seconds=1),
        }
    )
    assert jobs.record_frame(frame, [recovered]) == []
    job_id, snapshot = jobs.claim()
    assert snapshot.status == IncidentStatus.OPEN
    assert jobs.get_incident(error.incident_id).status == IncidentStatus.RECOVERED
    jobs.finish(job_id, result(snapshot))
    assert jobs.latest_job(error.incident_id)["status"] == "COMPLETED"
    assert jobs.latest_analysis(error.incident_id).status == "INSUFFICIENT_EVIDENCE"
    assert jobs.analysis_input(jobs.latest_analysis(error.incident_id)) == snapshot
    assert (
        jobs.analysis_input(
            result(snapshot).model_copy(update={"observed_facts": "다른 결과"})
        )
        is None
    )
    assert jobs.claim() is None
    assert jobs.record_frame(frame, [error])[0]["job_id"] == first["job_id"]


def test_failed_manual_retry_is_idempotent_and_not_automatic(jobs, frame):
    item = incident(frame)
    jobs.record_frame(frame, [item])
    job_id, snapshot = jobs.claim()
    jobs.finish(job_id, result(snapshot, "FAILED"))
    assert jobs.claim() is None
    request_id = str(uuid4())
    retried = jobs.retry(item.incident_id, request_id)
    assert jobs.retry(item.incident_id, request_id) == retried
    assert jobs.retry(item.incident_id, str(uuid4())) == retried
    job_id, snapshot = jobs.claim()
    jobs.finish(job_id, result(snapshot))
    assert jobs.retry(item.incident_id, request_id)["job_id"] == retried["job_id"]
    with pytest.raises(db.AnalysisConflictError):
        jobs.retry(item.incident_id, str(uuid4()))


def test_analysis_input_keeps_older_saved_report_separate_from_reanalysis(jobs, frame):
    item = incident(frame)
    jobs.record_frame(frame, [item])
    first_id, first_input = jobs.claim()
    first = result(first_input, "FAILED")
    jobs.finish(first_id, first)
    jobs.retry(item.incident_id, str(uuid4()))
    second_id, second_input = jobs.claim()
    second = result(second_input).model_copy(
        update={"generated_at": first.generated_at + timedelta(seconds=1)}
    )
    jobs.finish(second_id, second)
    assert jobs.analysis_input(first) == first_input
    assert jobs.analysis_input(second) == second_input
    assert (
        jobs.analysis_input(
            first.model_copy(update={"incident_id": "another-incident"})
        )
        is None
    )


def test_storage_only_error_and_recovery_never_create_work(jobs, frame):
    from weeing_weeing.db.models import TelemetryRow

    item = incident(frame)
    for _ in range(2):
        assert jobs.record_frame(frame, [item], enqueue_analysis=False) == []
    recovered = item.model_copy(
        update={
            "status": IncidentStatus.RECOVERED,
            "last_detected_at": item.last_detected_at + timedelta(seconds=1),
        }
    )
    assert jobs.record_frame(frame, [recovered], enqueue_analysis=False) == []
    assert jobs.get_incident(item.incident_id) == recovered
    assert jobs.latest_job(item.incident_id) is None
    assert jobs.claim() is None
    with jobs._transaction() as session:
        assert len(session.scalars(select(TelemetryRow)).all()) == 1
        assert session.scalar(select(AnalysisJobRow)) is None
        assert session.scalar(select(AnalysisRow)) is None


@pytest.mark.parametrize("enqueue_analysis", [False, True])
def test_deleted_incident_is_not_recreated_in_either_mode(
    jobs, frame, enqueue_analysis
):
    from weeing_weeing.db.models import DeletedIncidentRow

    item = incident(frame)
    with jobs._transaction() as session:
        session.add(
            DeletedIncidentRow(incident_id=item.incident_id, deleted_at=frame.timestamp)
        )
    assert jobs.record_frame(frame, [item], enqueue_analysis=enqueue_analysis) == []
    assert jobs.get_incident(item.incident_id) is None
    assert jobs.latest_job(item.incident_id) is None


def test_retry_stays_latest_when_clock_does_not_advance(jobs, frame, monkeypatch):
    from types import SimpleNamespace

    from weeing_weeing.db import analysis_jobs

    fixed_time = analysis_jobs.now()
    monkeypatch.setattr(analysis_jobs, "now", lambda: fixed_time)
    identifiers = iter(["f" * 32, "0" * 32])
    monkeypatch.setattr(
        analysis_jobs, "uuid4", lambda: SimpleNamespace(hex=next(identifiers))
    )
    item = incident(frame)
    original = jobs.record_frame(frame, [item])[0]
    job_id, snapshot = jobs.claim()
    jobs.finish(job_id, result(snapshot, "FAILED"))
    retried = jobs.retry(item.incident_id, "retry")
    assert retried["created_at"] > original["created_at"]
    assert jobs.latest_job(item.incident_id)["job_id"] == retried["job_id"]
    job_id, snapshot = jobs.claim()
    jobs.finish(job_id, result(snapshot))
    assert jobs.retry(item.incident_id, "retry")["job_id"] == retried["job_id"]
    with pytest.raises(db.AnalysisConflictError):
        jobs.retry(item.incident_id, "another-retry")


def test_restart_never_repeats_running_paid_call(jobs, frame):
    item = incident(frame)
    jobs.record_frame(frame, [item])
    jobs.claim()
    assert jobs.recover_interrupted() == 1
    assert jobs.latest_job(item.incident_id)["error_code"] == "interrupted"
    assert jobs.claim() is None


def test_result_mismatch_rolls_back_both_result_and_job(jobs, frame):
    item = incident(frame)
    jobs.record_frame(frame, [item])
    job_id, snapshot = jobs.claim()
    wrong = result(snapshot).model_copy(update={"incident_id": "other"})
    with pytest.raises(db.AnalysisConflictError):
        jobs.finish(job_id, wrong)
    assert jobs.latest_analysis(item.incident_id) is None
    assert jobs.latest_job(item.incident_id)["status"] == "RUNNING"


def test_queue_overflow_is_explicit_and_does_not_drop_event(jobs, frame):
    item = incident(frame)
    job = jobs.record_frame(frame, [item], capacity=0)[0]
    assert job["status"] == "FAILED"
    assert job["error_code"] == "queue_full"
    assert jobs.get_incident(item.incident_id) == item
    assert jobs.claim() is None


def test_pending_survives_reopen(jobs, frame):
    item = incident(frame)
    jobs.record_frame(frame, [item])
    reopened = db.SqlAnalysisJobs(jobs._engine)
    assert reopened.recover_interrupted() == 0
    assert reopened.claim()[1] == item


@pytest.mark.parametrize("enqueue_analysis", [False, True])
def test_job_and_sensor_roll_back_when_incident_insert_fails(
    jobs, frame, enqueue_analysis
):
    # 같은 트랜잭션 중간의 DB 제약 위반을 재현한다.
    from sqlalchemy.exc import IntegrityError

    from weeing_weeing.db.models import TelemetryRow

    invalid = incident(frame).model_copy(update={"asset_id": None})
    with pytest.raises(IntegrityError):
        jobs.record_frame(frame, [invalid], enqueue_analysis=enqueue_analysis)
    with jobs._transaction() as session:
        assert session.scalar(select(TelemetryRow)) is None
        assert session.scalar(select(AnalysisJobRow)) is None
        assert session.scalar(select(AnalysisRow)) is None
