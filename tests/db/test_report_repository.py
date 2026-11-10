from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from threading import Event
from time import sleep
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, select, text, update

from weeing_weeing.api.report_index import process_pending_reports
from weeing_weeing.contracts import (
    Incident,
    ReportDraft,
    ReportFormData,
    Role,
    TelemetryRecord,
    UserAccount,
)
from weeing_weeing.db import interface as db
from weeing_weeing.db.models import (
    ApprovalRow,
    IncidentRow,
    ReportIndexJobRow,
    ReportRow,
    ReportVersionRow,
)

T0 = datetime(2026, 10, 28, 9, tzinfo=timezone.utc)


@pytest.fixture
def setup_reports(reports, database_url):

    users = db.open_users(database_url)
    for employee, role in (
        ("I1", Role.INSPECTOR),
        ("I2", Role.INSPECTOR),
        ("L1", Role.MAINT_LEAD),
        ("C1", Role.CONTROL),
        ("S1", Role.SITE_MANAGER),  # 관리자
        ("S2", Role.SITE_MANAGER),
    ):
        users.create_user(
            UserAccount(
                employee_no=employee,
                name=employee,
                role=role,
                is_admin=employee == "S1",
            ),
            "test-password-123",
        )
    incidents = db.open_incidents(database_url)
    incidents.save_incident(
        Incident(
            incident_id="INC-1",
            process_id="P1",
            asset_id="A1",
            codes=["BTT2-P03"],
            severity="Error",
            first_detected_at=T0,
            last_detected_at=T0,
        )
    )
    yield reports
    users._engine.dispose()
    incidents._engine.dispose()


def ready_draft(incident_id="INC-1"):
    return ReportDraft(
        incident_id=incident_id,
        data_origin="SYNTHETIC",
        form_data=ReportFormData(
            actual_actions="센서 청소",
            action_at=T0,
            confirmed_cause="렌즈 오염",
            trial_details="빈 이송 시험 정상",
            trial_result="정상",
        ),
    )


def add_incident(repo, incident_id):
    from weeing_weeing.db.incidents import SqlIncidents

    SqlIncidents(repo._engine).save_incident(
        Incident(
            incident_id=incident_id,
            process_id="P1",
            asset_id="A1",
            codes=["BTT2-P03"],
            severity="Error",
            first_detected_at=T0,
            last_detected_at=T0,
        )
    )


def step(repo, doc, actor, action, **kwargs):
    return repo.transition(
        actor, doc.report_id, action, expected_revision=doc.revision, **kwargs
    )


def approve(repo, doc):
    doc = step(repo, doc, "I1", "submit")
    doc = step(repo, doc, "L1", "review")
    return step(repo, doc, "C1", "approve")


@pytest.mark.parametrize(
    "state",
    ["DRAFT", "SUBMITTED", "REVIEWED", "REJECTED", "APPROVED", "HISTORICAL_APPROVED"],
)
def test_analysis_retry_stops_only_after_final_report_approval(
    setup_reports, sample_rows, state
):
    reports = setup_reports
    jobs = db.SqlAnalysisJobs(reports._engine)
    item = jobs.get_incident("INC-1")
    jobs.record_frame(TelemetryRecord.model_validate(sample_rows[0]), [item])
    job_id, _ = jobs.claim()
    jobs.fail(job_id, "fake-timeout")
    doc = reports.create_draft("I1", ready_draft())
    if state != "DRAFT":
        doc = step(reports, doc, "I1", "submit")
    if state == "REJECTED":
        doc = step(reports, doc, "L1", "reject", comment="내용 보완")
    elif state in ("REVIEWED", "APPROVED", "HISTORICAL_APPROVED"):
        doc = step(reports, doc, "L1", "review")
        if state != "REVIEWED":
            doc = step(reports, doc, "C1", "approve")
    blocked = state in ("APPROVED", "HISTORICAL_APPROVED")
    if state == "HISTORICAL_APPROVED":
        legacy_revision(reports, doc)
    assert jobs.has_approved_report(item.incident_id) == blocked
    if blocked:
        with pytest.raises(db.AnalysisConflictError, match="최종 승인"):
            jobs.retry(item.incident_id, "retry", expected_job_id=job_id)
        assert jobs.latest_job(item.incident_id)["job_id"] == job_id
    else:
        assert jobs.retry(item.incident_id, "retry")["status"] == "PENDING"


def test_queued_analysis_retry_is_not_started_after_report_approval(
    setup_reports, sample_rows
):
    reports = setup_reports
    jobs = db.SqlAnalysisJobs(reports._engine)
    item = jobs.get_incident("INC-1")
    jobs.record_frame(TelemetryRecord.model_validate(sample_rows[0]), [item])
    original_id, _ = jobs.claim()
    jobs.fail(original_id, "fake-timeout")
    retry = jobs.retry(item.incident_id, "retry")
    doc = reports.create_draft("I1", ready_draft())
    approve(reports, doc)
    # 응답을 잃어버린 동일 요청은 새 작업을 만들지 않고 접수된 작업만 반환한다.
    assert jobs.retry(item.incident_id, "retry")["job_id"] == retry["job_id"]
    assert jobs.claim() is None
    assert jobs.latest_job(item.incident_id)["error_code"] == "report_approved"
    with pytest.raises(db.AnalysisConflictError, match="최종 승인"):
        jobs.retry(item.incident_id, "another-retry")


def legacy_revision(repo, approved):
    """이전 정책에서 승인 후 개정된 기록을 만들어 기존 데이터 호환성을 검사한다."""
    with repo._transaction() as session:
        if repo._engine.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        row = session.scalar(
            select(ReportRow)
            .where(ReportRow.report_id == approved.report_id)
            .with_for_update()
        )
        old = session.get(ReportVersionRow, (row.report_id, row.current_version))
        data = deepcopy(old.data)
        data["report"] = None
        row.current_version += 1
        row.report_status = "DRAFT"
        row.revision += 1
        session.add(
            ReportVersionRow(
                report_id=row.report_id,
                version_no=row.current_version,
                author_name=old.author_name,
                report_status="DRAFT",
                data_origin=old.data_origin,
                data=data,
                created_at=T0,
                updated_at=T0,
            )
        )
    return repo.get_report("I1", approved.report_id)


def test_requeue_indexed_reports_only_latest_indexed(setup_reports):
    repo = setup_reports
    first = approve(repo, repo.create_draft("I1", ready_draft()))
    repo.record_index_result(first.report_id, first.report_version, success=True)
    add_incident(repo, "INC-2")
    second = approve(repo, repo.create_draft("I1", ready_draft("INC-2")))
    repo.record_index_result(second.report_id, second.report_version, success=False)

    # 실패 작업은 그대로 두고 indexed만 다시 대기로 돌린다.
    assert repo.requeue_indexed_reports() == 1
    assert repo.get_report("I1", first.report_id).index_status == "pending"
    assert repo.get_report("I1", second.report_id).index_status == "failed"
    assert [r.report_id for r in repo.pending_index_reports()] == [first.report_id]
    assert repo.requeue_indexed_reports() == 0


def test_index_job_result_and_failed_retry(setup_reports):
    repo = setup_reports
    first = approve(repo, repo.create_draft("I1", ready_draft()))
    assert first.index_status == "pending"
    assert [r.report_id for r in repo.pending_index_reports()] == [first.report_id]
    repo.record_index_result(first.report_id, first.report_version, success=True)
    repo.record_index_result(first.report_id, first.report_version, success=True)
    repo.record_index_result(first.report_id, first.report_version, success=False)
    assert repo.get_report("I1", first.report_id).index_status == "indexed"
    assert repo.pending_index_reports(include_failed=True) == []

    add_incident(repo, "INC-2")
    second = approve(repo, repo.create_draft("I1", ready_draft("INC-2")))
    repo.record_index_result(second.report_id, second.report_version, success=False)
    assert repo.get_report("I1", second.report_id).index_status == "failed"
    assert repo.pending_index_reports() == []
    assert [r.report_id for r in repo.pending_index_reports(include_failed=True)] == [
        second.report_id
    ]
    repo.record_index_result(second.report_id, second.report_version, success=True)
    assert repo.get_report("I1", second.report_id).index_status == "indexed"


def test_document_upload_rejects_an_existing_report_id(setup_reports):
    from weeing_weeing.db.documents import SqlDocuments

    report = setup_reports.create_draft("I1", ready_draft())
    documents = SqlDocuments(setup_reports._engine)
    assert "보고서" in documents.upload_conflict(report.report_id, "pdf-sha")


def test_approval_waits_for_vector_write_of_same_report(setup_reports):
    repo = setup_reports
    first = approve(repo, repo.create_draft("I1", ready_draft()))
    writes = []
    writing = Event()
    release = Event()
    revising = Event()

    class PausingIndexer:
        def index_report(self, report):
            writes.append(report.report_version)
            if report.report_version == 1:
                writing.set()
                assert release.wait(3)
            return 1

    def revise_and_approve():
        revising.set()
        revised = legacy_revision(repo, first)
        return approve(repo, revised)

    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(process_pending_reports, repo, PausingIndexer)
        assert writing.wait(3)
        revision = pool.submit(revise_and_approve)
        assert revising.wait(3)
        sleep(0.1)
        assert not revision.done()
        release.set()
        assert worker.result(timeout=5).indexed == 1
        second = revision.result(timeout=5)
    assert second.report_version == 2
    assert process_pending_reports(repo, PausingIndexer).indexed == 1
    assert writes == [1, 2]
    latest = repo.get_report("I1", first.report_id)
    assert latest.report_version == 2
    assert latest.index_status == "indexed"
    assert repo.pending_index_reports() == []


def test_draft_round_trip_owner_and_revision(setup_reports):
    repo = setup_reports
    doc = repo.create_draft("I1", ReportDraft(incident_id="INC-1"))
    assert repo.get_report("I1", doc.report_id) == doc
    assert repo.list_reports("I2") == []
    assert repo.get_report("I2", doc.report_id) == doc
    assert repo.get_report("L1", doc.report_id) == doc
    with pytest.raises(db.ReportForbiddenError):
        repo.save_draft(
            "I2", doc.report_id, ready_draft(), expected_revision=doc.revision
        )
    changed = repo.save_draft(
        "I1", doc.report_id, ready_draft(), expected_revision=doc.revision
    )
    assert changed.revision == doc.revision + 1
    with pytest.raises(db.ReportConflictError):
        repo.save_draft(
            "I1",
            doc.report_id,
            ReportDraft(incident_id="INC-1"),
            expected_revision=doc.revision,
        )
    assert repo.get_report("I1", doc.report_id).form_data.actual_actions == "센서 청소"


def test_complete_workflow_has_immutable_contract_and_atomic_outbox(setup_reports):
    repo = setup_reports
    doc = repo.create_draft("I1", ready_draft())
    assert repo.pending_index_reports() == []
    doc = step(repo, doc, "I1", "submit")
    assert repo.list_reports("L1", review=True)[0].report_id == doc.report_id
    assert repo.list_reports("C1", review=True) == []
    assert doc.report.maintenance.actions_taken[0].by == "I1"
    with pytest.raises(db.ReportConflictError):
        repo.save_draft(
            "I1",
            doc.report_id,
            ReportDraft(incident_id="INC-1"),
            expected_revision=doc.revision,
        )
    doc = step(repo, doc, "L1", "review")
    assert repo.pending_index_reports() == []
    doc = step(repo, doc, "C1", "approve")
    assert doc.report_status == "APPROVED" and doc.index_status == "pending"
    assert [a.user for a in doc.approval] == ["I1", "L1", "C1"]
    assert doc.report.approval == doc.approval
    assert repo.pending_index_reports() == [doc.report]
    with pytest.raises(db.ReportConflictError):
        step(repo, doc, "C1", "approve")
    with repo._engine.connect() as conn:
        assert len(conn.execute(select(ReportIndexJobRow)).all()) == 1
        assert len(conn.execute(select(ApprovalRow)).all()) == 3


@pytest.mark.parametrize(
    "actor,action",
    [("C1", "review"), ("I2", "review"), ("I1", "review")],
)
def test_wrong_role_or_author_cannot_approve(setup_reports, actor, action):
    repo = setup_reports
    doc = step(repo, repo.create_draft("I1", ready_draft()), "I1", "submit")
    with pytest.raises(db.ReportForbiddenError):
        step(repo, doc, actor, action)
    assert len(repo.get_report("I1", doc.report_id).approval) == 1


def test_admin_has_every_role_permission(setup_reports):
    """D-36: S1은 현장 책임자 + 관리자. 직책과 관계없이 모든 결재 단계를 할 수 있다."""
    repo = setup_reports
    doc = step(repo, repo.create_draft("I1", ready_draft()), "I1", "submit")
    assert [r.report_id for r in repo.list_reports("S1", review=True)] == [
        doc.report_id
    ]
    doc = step(repo, doc, "S1", "review")
    assert [r.report_id for r in repo.list_reports("S1", review=True)] == [
        doc.report_id
    ]
    doc = step(repo, doc, "S1", "approve")
    assert doc.report_status == "APPROVED"
    # 이력은 실제 결재자 사번과 그 단계의 직책으로 남는다.
    assert [(a.user, a.role) for a in doc.approval] == [
        ("I1", Role.INSPECTOR),
        ("S1", Role.MAINT_LEAD),
        ("S1", Role.CONTROL),
    ]
    assert len(repo.review_history("S1")) == 1
    assert repo.list_reports("S1", review=True) == []


def test_admin_writes_reports_but_cannot_approve_own(setup_reports):
    repo = setup_reports
    doc = step(repo, repo.create_draft("S1", ready_draft()), "S1", "submit")
    assert doc.report_status == "SUBMITTED"
    assert repo.list_reports("S1", review=True) == []  # 본인 보고서는 결재 대기에 없다
    with pytest.raises(db.ReportForbiddenError):
        step(repo, doc, "S1", "review")
    doc = step(repo, doc, "L1", "review")
    with pytest.raises(db.ReportForbiddenError):
        step(repo, doc, "S1", "approve")


def test_non_admin_site_manager_has_no_report_role(setup_reports):
    repo = setup_reports  # S2는 S1과 같은 직책이지만 관리자가 아니다
    with pytest.raises(db.ReportForbiddenError):
        repo.create_draft("S2", ready_draft())
    doc = step(repo, repo.create_draft("I1", ready_draft()), "I1", "submit")
    with pytest.raises(db.ReportForbiddenError):
        step(repo, doc, "S2", "review")
    with pytest.raises(db.ReportForbiddenError):
        repo.list_reports("S2", review=True)


def test_missing_incident_or_incomplete_form_cannot_submit(setup_reports):
    repo = setup_reports
    with pytest.raises(ValueError, match="사건을 선택"):
        repo.create_draft("I1", ReportDraft())
    for draft in (ReportDraft(incident_id="INC-1"),):
        doc = repo.create_draft("I1", draft)
        with pytest.raises(ValueError):
            step(repo, doc, "I1", "submit")
        unchanged = repo.get_report("I1", doc.report_id)
        assert unchanged.revision == 1 and unchanged.approval == []
    with pytest.raises(db.UnknownIncidentError):
        repo.create_draft("I1", ReportDraft(incident_id="missing"))


def test_rejection_reason_revision_and_history(setup_reports):
    repo = setup_reports
    doc = step(repo, repo.create_draft("I1", ready_draft()), "I1", "submit")
    with pytest.raises(ValueError):
        step(repo, doc, "L1", "reject")
    old = step(repo, doc, "L1", "reject", comment="시험 결과 보완")
    new = repo.revise("I1", old.report_id, expected_revision=old.revision)
    assert new.report_version == 2 and new.approval == [] and new.report is None
    assert repo.get_report("I1", old.report_id, version=1).report == old.report
    assert repo.get_report("I2", old.report_id, version=1).report == old.report
    assert repo.get_report("I2", old.report_id).report_version == 2
    with pytest.raises(db.ReportForbiddenError):
        repo.revise("I2", old.report_id, expected_revision=new.revision)


@pytest.mark.parametrize("actor", ["I2", "L1", "C1", "S1"])
@pytest.mark.parametrize(
    "state", ["DRAFT", "SUBMITTED", "REVIEWED", "APPROVED", "REJECTED"]
)
def test_all_active_roles_can_read_and_list_every_report_state(
    setup_reports, actor, state
):
    repo = setup_reports
    doc = repo.create_draft("I1", ready_draft())
    if state != "DRAFT":
        doc = step(repo, doc, "I1", "submit")
    if state == "REJECTED":
        doc = step(repo, doc, "L1", "reject", comment="내용 보완")
    elif state in {"REVIEWED", "APPROVED"}:
        doc = step(repo, doc, "L1", "review")
        if state == "APPROVED":
            doc = step(repo, doc, "C1", "approve")
    assert repo.get_report(actor, doc.report_id) == doc
    assert [row.report_id for row in repo.list_reports(actor, all_reports=True)] == [
        doc.report_id
    ]
    assert repo.list_reports(actor) == []  # 내 보고서 필터는 계속 본인 것만
    with pytest.raises(db.ReportForbiddenError):
        repo.save_draft(
            actor, doc.report_id, ready_draft(), expected_revision=doc.revision
        )


def test_all_reports_cannot_bypass_review_queue_role(setup_reports):
    with pytest.raises(ValueError):
        setup_reports.list_reports("I2", review=True, all_reports=True)


def test_new_approved_version_replaces_pending_selection_only(setup_reports):
    repo = setup_reports
    old = approve(repo, repo.create_draft("I1", ready_draft()))
    new = legacy_revision(repo, old)
    assert repo.pending_index_reports() == [old.report]
    new = approve(repo, new)
    assert [r.report_version for r in repo.pending_index_reports()] == [2]
    assert repo.get_report("C1", old.report_id, version=1).report == old.report


def test_snapshot_is_not_replaced_when_live_incident_changes(setup_reports):
    repo = setup_reports
    doc = repo.create_draft("I1", ready_draft())
    with repo._engine.begin() as conn:
        changed = doc.incident.model_dump(mode="json") | {"asset_id": "A2"}
        conn.execute(
            update(IncidentRow)
            .where(IncidentRow.incident_id == "INC-1")
            .values(data=changed, asset_id="A2")
        )
    assert repo.get_report("I1", doc.report_id).incident == doc.incident
    assert repo.get_report("I1", doc.report_id).incident.asset_id == "A1"


def test_action_time_is_never_inferred_and_nonperformance_is_not_an_action(
    setup_reports,
):
    repo = setup_reports
    draft = ready_draft()
    draft.form_data.action_at = None
    doc = repo.create_draft("I1", draft)
    with pytest.raises(ValueError, match="조치 시각"):
        step(repo, doc, "I1", "submit")
    draft.form_data.action_status = "미수행"
    draft.form_data.actual_actions = "예비 부품 입고 대기"
    doc = repo.save_draft("I1", doc.report_id, draft, expected_revision=doc.revision)
    submitted = step(repo, doc, "I1", "submit")
    assert submitted.report.maintenance.actions_taken == []
    assert "예비 부품 입고 대기" in submitted.report.maintenance.remarks


def test_stale_concurrent_actions_cannot_duplicate_approval(setup_reports):
    repo = setup_reports
    doc = step(repo, repo.create_draft("I1", ready_draft()), "I1", "submit")

    def review(_):
        try:
            step(repo, doc, "L1", "review")
            return "ok"
        except (db.ReportConflictError, db.DatabaseUnavailableError):
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(review, range(2))) == ["conflict", "ok"]
    assert len(repo.get_report("I1", doc.report_id).approval) == 2


def test_outbox_failure_rolls_back_final_approval(setup_reports):
    repo = setup_reports
    doc = step(repo, repo.create_draft("I1", ready_draft()), "I1", "submit")
    doc = step(repo, doc, "L1", "review")

    def fail_job(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO report_index_job"):
            raise RuntimeError("simulated storage failure")

    event.listen(repo._engine, "before_cursor_execute", fail_job)
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            step(repo, doc, "C1", "approve")
    finally:
        event.remove(repo._engine, "before_cursor_execute", fail_job)
    unchanged = repo.get_report("I1", doc.report_id)
    assert unchanged.report_status == "REVIEWED"
    assert unchanged.revision == doc.revision
    assert len(unchanged.approval) == 2
    assert repo.pending_index_reports() == []


def test_migration_matches_models(setup_reports):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from weeing_weeing.db.models import Base

    with setup_reports._engine.connect() as connection:
        assert (
            compare_metadata(MigrationContext.configure(connection), Base.metadata)
            == []
        )


def test_approved_reports_are_complete_latest_approved_independent_of_index_state(
    setup_reports,
):
    repo = setup_reports
    first = approve(repo, repo.create_draft("I1", ready_draft()))
    add_incident(repo, "INC-2")
    add_incident(repo, "INC-3")
    second = approve(repo, repo.create_draft("I1", ready_draft("INC-2")))
    repo.record_index_result(first.report_id, first.report_version, success=True)
    repo.record_index_result(second.report_id, second.report_version, success=False)
    draft = legacy_revision(repo, first)
    rejected = step(
        repo,
        step(repo, repo.create_draft("I1", ready_draft("INC-3")), "I1", "submit"),
        "L1",
        "reject",
        comment="보완",
    )
    values = {r.report_id: r for r in repo.approved_reports()}
    assert set(values) == {first.report_id, second.report_id}
    assert (
        values[first.report_id].report_version == 1
    )  # 현재 초안이 승인 판을 가리지 않는다.
    assert rejected.report_id not in values
    summaries = {r.report_id: r for r in repo.list_reports("I2", approved_only=True)}
    assert set(summaries) == {first.report_id, second.report_id}
    assert summaries[first.report_id].report_version == 1
    assert summaries[first.report_id].report_status == "APPROVED"
    revised = approve(repo, draft)
    values = {r.report_id: r for r in repo.approved_reports()}
    assert values[first.report_id].report_version == revised.report_version == 2
    summaries = {r.report_id: r for r in repo.list_reports("I2", approved_only=True)}
    assert summaries[first.report_id].report_version == 2


def test_report_number_sequence_and_incident_cannot_change(setup_reports):
    repo = setup_reports
    for incident_id in ("INC-2", "INC-3", "INC-4"):
        add_incident(repo, incident_id)
    with ThreadPoolExecutor(max_workers=4) as pool:
        docs = list(
            pool.map(
                lambda incident_id: repo.create_draft("I1", ready_draft(incident_id)),
                ("INC-1", "INC-2", "INC-3", "INC-4"),
            )
        )
    prefix = (
        f"RPT-BTT2-P03-{docs[0].created_at.astimezone(ZoneInfo('Asia/Seoul')):%Y%m%d}-"
    )
    assert {doc.report_id for doc in docs} == {f"{prefix}{i:03d}" for i in range(1, 5)}
    with pytest.raises(ValueError, match="사건을 선택"):
        repo.save_draft(
            "I1", docs[0].report_id, ReportDraft(), expected_revision=docs[0].revision
        )
    with pytest.raises(db.ReportConflictError, match="변경할 수 없습니다"):
        repo.save_draft(
            "I1",
            docs[0].report_id,
            ReportDraft(incident_id="other"),
            expected_revision=docs[0].revision,
        )


def test_concurrent_report_creation_allows_only_one_per_incident(setup_reports):
    repo = setup_reports

    def create(_):
        try:
            return repo.create_draft("I1", ready_draft())
        except db.ReportConflictError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(4)))
    assert len([item for item in results if item is not None]) == 1
    assert len(repo.list_reports("I1")) == 1


def test_incident_delete_racing_sensor_update_does_not_restore_incident(
    setup_reports, database_url, sample_rows
):
    from weeing_weeing.contracts import TelemetryRecord

    repo = setup_reports
    report = approve(repo, repo.create_draft("I1", ready_draft()))
    incidents = db.open_incidents(database_url)
    jobs = db.open_analysis_jobs(database_url)
    incident = incidents.get_incident("INC-1")
    frame = TelemetryRecord.model_validate(sample_rows[0]).model_copy(
        update={
            "record_id": "race-delete",
            "timestamp": T0,
            "process_id": "P1",
            "asset_id": "A1",
        }
    )
    deleting, release = Event(), Event()

    def delete_vector(report_id):
        assert report_id == report.report_id
        deleting.set()
        assert release.wait(5)
        return 1

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            deletion = pool.submit(
                repo.delete_incident, "C1", "INC-1", delete_vector=delete_vector
            )
            assert deleting.wait(3)
            update_future = pool.submit(jobs.record_frame, frame, [incident])
            sleep(0.1)
            assert not update_future.done()
            release.set()
            assert deletion.result(timeout=5)["deleted_reports"] == 1
            assert update_future.result(timeout=5) == []
        assert incidents.get_incident("INC-1") is None
    finally:
        release.set()
        incidents._engine.dispose()
        jobs._engine.dispose()


def test_legacy_unlinked_draft_cannot_be_attached_to_occupied_incident(setup_reports):
    repo = setup_reports
    repo.create_draft("I1", ready_draft())
    add_incident(repo, "INC-2")
    legacy = repo.create_draft("I1", ready_draft("INC-2"))
    with repo._transaction() as session:
        session.execute(
            update(ReportRow)
            .where(ReportRow.report_id == legacy.report_id)
            .values(incident_id=None)
        )
    with pytest.raises(db.ReportConflictError, match="이미 보고서"):
        repo.save_draft(
            "I1", legacy.report_id, ready_draft(), expected_revision=legacy.revision
        )


def test_same_error_code_shares_sequence_across_different_incidents(
    setup_reports, database_url
):
    repo = setup_reports
    incidents = db.open_incidents(database_url)
    try:
        incidents.save_incident(
            Incident(
                incident_id="INC-2",
                process_id="P1",
                asset_id="A1",
                codes=["BTT2-P03", "BTT2-P04"],
                severity="Error",
                first_detected_at=T0,
                last_detected_at=T0,
            )
        )

        def create(incident_id):
            draft = ready_draft()
            draft.incident_id = incident_id
            return repo.create_draft("I1", draft)

        for incident_id in ("INC-3", "INC-4"):
            add_incident(repo, incident_id)
        with ThreadPoolExecutor(max_workers=4) as pool:
            docs = list(pool.map(create, ["INC-1", "INC-2", "INC-3", "INC-4"]))
        prefix = f"RPT-BTT2-P03-{docs[0].created_at.astimezone(ZoneInfo('Asia/Seoul')):%Y%m%d}-"
        assert {doc.report_id for doc in docs} == {
            f"{prefix}{i:03d}" for i in range(1, 5)
        }
    finally:
        incidents._engine.dispose()
