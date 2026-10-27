from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select, update

from weeing_weeing.contracts import (
    Incident,
    ReportDraft,
    ReportFormData,
    Role,
    UserAccount,
)
from weeing_weeing.db import interface as db
from weeing_weeing.db.models import ApprovalRow, IncidentRow, ReportIndexJobRow

T0 = datetime(2026, 10, 28, 9, tzinfo=timezone.utc)


@pytest.fixture
def setup_reports(reports, database_url, monkeypatch):
    from weeing_weeing.db import users as module

    monkeypatch.setattr(module, "SCRYPT_N", 2**10)
    users = db.open_users(database_url)
    for employee, role in (
        ("I1", Role.INSPECTOR),
        ("I2", Role.INSPECTOR),
        ("L1", Role.MAINT_LEAD),
        ("C1", Role.CONTROL),
        ("S1", Role.SITE_MANAGER),
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


def ready_draft():
    return ReportDraft(
        incident_id="INC-1",
        data_origin="SYNTHETIC",
        form_data=ReportFormData(
            actual_actions="센서 청소",
            action_at=T0,
            confirmed_cause="렌즈 오염",
            trial_details="빈 이송 시험 정상",
            trial_result="정상",
        ),
    )


def step(repo, doc, actor, action, **kwargs):
    return repo.transition(
        actor, doc.report_id, action, expected_revision=doc.revision, **kwargs
    )


def approve(repo, doc):
    doc = step(repo, doc, "I1", "submit")
    doc = step(repo, doc, "L1", "review")
    return step(repo, doc, "C1", "approve")


def test_draft_round_trip_owner_and_revision(setup_reports):
    repo = setup_reports
    doc = repo.create_draft("I1", ReportDraft())
    assert repo.get_report("I1", doc.report_id) == doc
    assert repo.list_reports("I2") == []
    with pytest.raises(db.ReportForbiddenError):
        repo.get_report("I2", doc.report_id)
    with pytest.raises(db.ReportForbiddenError):
        repo.get_report("L1", doc.report_id)
    changed = repo.save_draft(
        "I1", doc.report_id, ready_draft(), expected_revision=doc.revision
    )
    assert changed.revision == doc.revision + 1
    with pytest.raises(db.ReportConflictError):
        repo.save_draft(
            "I1", doc.report_id, ReportDraft(), expected_revision=doc.revision
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
            "I1", doc.report_id, ReportDraft(), expected_revision=doc.revision
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
    [("S1", "review"), ("C1", "review"), ("I2", "review"), ("I1", "review")],
)
def test_admin_flag_does_not_grant_business_approval(setup_reports, actor, action):
    repo = setup_reports
    doc = step(repo, repo.create_draft("I1", ready_draft()), "I1", "submit")
    with pytest.raises(db.ReportForbiddenError):
        step(repo, doc, actor, action)
    assert len(repo.get_report("I1", doc.report_id).approval) == 1


def test_missing_incident_or_incomplete_form_cannot_submit(setup_reports):
    repo = setup_reports
    for draft in (ReportDraft(), ReportDraft(incident_id="INC-1")):
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
    with pytest.raises(db.ReportForbiddenError):
        repo.revise("I2", old.report_id, expected_revision=new.revision)


def test_new_approved_version_replaces_pending_selection_only(setup_reports):
    repo = setup_reports
    old = approve(repo, repo.create_draft("I1", ready_draft()))
    new = repo.revise("I1", old.report_id, expected_revision=old.revision)
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
