"""보고서 저장·결재(#62). 권한·상태·revision 검사와 기록은 같은 트랜잭션에서 처리한다."""

import hashlib
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text, update

from weeing_weeing.contracts import (
    AnalysisResult,
    Incident,
    MaintenanceReport,
    ReportDocument,
    ReportDraft,
    ReportFormData,
    ReportStatus,
    ReportSummary,
    Role,
)
from weeing_weeing.contracts.report import (
    ActionTaken,
    ApprovalStep,
    MaintenanceRecord,
    TimeRange,
    TrialRun,
)
from weeing_weeing.db.incidents import UnknownIncidentError
from weeing_weeing.db.models import (
    AnalysisRow,
    ApprovalRow,
    DeletedReportNumberRow,
    IncidentRow,
    ReportIndexJobRow,
    ReportRow,
    ReportVersionRow,
    UserRow,
)
from weeing_weeing.db.session import Repository, now, utc


class ReportNotFoundError(LookupError):
    """보고서 또는 지정한 버전이 없다."""


class ReportForbiddenError(PermissionError):
    """작성자 또는 직책 조건을 충족하지 않는다."""


class ReportConflictError(ValueError):
    """이전 revision 또는 잘못된 상태 전환. 자동 재전송하지 않는다."""


@dataclass(frozen=True)
class ReportIndexWork:
    """보고서 행 잠금을 유지하는 동안 벡터 저장 결과를 같은 DB 거래에 기록한다."""

    report: MaintenanceReport
    finish: Callable[[bool], None]


@dataclass(frozen=True)
class ReportReviewHistory:
    """현재 보고서 요약과 결재자가 마지막으로 처리한 버전의 이력."""

    report: ReportSummary
    review_version: int
    review_step: int
    review_role: str
    decision: str
    reviewed_at: datetime


def _actor(session, employee_no: str, role: Role | None = None) -> UserRow:
    user = session.get(UserRow, employee_no)
    if user is None or not user.is_active or (role and user.role != role.value):
        raise ReportForbiddenError("이 작업을 할 수 있는 활성 계정이 아닙니다.")
    return user


def _author(session, employee_no: str) -> UserRow:
    user = _actor(session, employee_no)
    if user.role not in (Role.INSPECTOR.value, Role.MAINT_LEAD.value):
        raise ReportForbiddenError(
            "현장 점검자와 보전 팀장만 보고서를 작성할 수 있습니다."
        )
    return user


def _load(session, report_id: str, version: int | None = None, *, lock=False):
    query = select(ReportRow).where(ReportRow.report_id == report_id)
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ReportNotFoundError("보고서를 찾을 수 없습니다.")
    content = session.get(
        ReportVersionRow,
        (report_id, row.current_version if version is None else version),
    )
    if content is None:
        raise ReportNotFoundError("해당 보고서 버전을 찾을 수 없습니다.")
    return row, content


def _owner(row: ReportRow, user: UserRow) -> None:
    if row.author_id != user.employee_no:
        raise ReportForbiddenError("작성자만 수정·제출·개정할 수 있습니다.")


def _claim(session, row: ReportRow, expected: int, **changes) -> None:
    if expected != row.revision:
        raise ReportConflictError(
            "다른 작업으로 보고서가 변경됐습니다. 다시 불러오세요."
        )
    result = session.execute(
        update(ReportRow)
        .where(ReportRow.report_id == row.report_id, ReportRow.revision == expected)
        .values(revision=expected + 1, updated_at=now(), **changes)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise ReportConflictError(
            "다른 작업으로 보고서가 변경됐습니다. 다시 불러오세요."
        )
    session.refresh(row)


def _snapshots(session, incident_id: str | None) -> dict:
    if incident_id is None:
        return {"incident": None, "ai_analysis": None}
    incident = session.get(IncidentRow, incident_id)
    if incident is None:
        raise UnknownIncidentError(incident_id)
    analysis = session.scalar(
        select(AnalysisRow)
        .where(AnalysisRow.incident_id == incident_id)
        .order_by(AnalysisRow.generated_at.desc(), AnalysisRow.id.desc())
        .limit(1)
    )
    return {
        "incident": deepcopy(incident.data),
        "ai_analysis": None if analysis is None else deepcopy(analysis.data),
    }


def _approvals(session, version: ReportVersionRow) -> list[ApprovalStep]:
    rows = session.scalars(
        select(ApprovalRow)
        .where(
            ApprovalRow.report_id == version.report_id,
            ApprovalRow.version_no == version.version_no,
        )
        .order_by(ApprovalRow.step)
    )
    return [
        ApprovalStep(
            step=a.step,
            role=a.role,
            user=a.employee_no,
            decision=a.decision,
            comment=a.comment,
            at=utc(a.at),
        )
        for a in rows
    ]


def _view(session, row: ReportRow, version: ReportVersionRow) -> ReportDocument:
    data = version.data
    job = session.get(ReportIndexJobRow, (row.report_id, version.version_no))
    return ReportDocument(
        report_id=row.report_id,
        author_id=row.author_id,
        author_name=version.author_name,
        report_version=version.version_no,
        current_version=row.current_version,
        report_status=version.report_status,
        revision=row.revision,
        data_origin=version.data_origin,
        incident_id=(data["incident"] or {}).get("incident_id"),
        incident=data["incident"],
        ai_analysis=data["ai_analysis"],
        form_data=data["form_data"],
        report=data.get("report"),
        approval=_approvals(session, version),
        index_status=None if job is None else job.status,
        created_at=utc(version.created_at),
        updated_at=utc(version.updated_at),
    )


def _submitted_report(row: ReportRow, version: ReportVersionRow) -> MaintenanceReport:
    data = version.data
    form = ReportFormData.model_validate(data["form_data"])
    if data["incident"] is None:
        raise ValueError("제출하려면 저장된 사건을 연결해야 합니다.")
    for label, value in (
        ("실제 수행 내용 또는 미수행 사유", form.actual_actions),
        ("확인 원인 또는 미확인 사유", form.confirmed_cause),
        ("복구 시험 내용·결과 또는 미실시 사유", form.trial_details),
    ):
        if not value.strip():
            raise ValueError(f"{label}를 입력하세요.")
    if (form.downtime_start is None) != (form.downtime_end is None):
        raise ValueError("정지시간은 시작·복귀 시각을 모두 입력하세요.")
    if form.action_status == "수행" and form.action_at is None:
        raise ValueError("실제 조치를 수행했다면 조치 시각을 입력하세요.")
    incident = Incident.model_validate(data["incident"])
    remarks = "\n".join(
        [
            f"부서: {form.department}",
            f"조치 여부: {form.action_status}",
            f"실제 조치 또는 미수행 사유: {form.actual_actions}",
            f"공정 영향: {form.process_impact}",
            f"원인 확인 근거: {form.cause_evidence}",
            f"시험 내용: {form.trial_details}",
            f"처리 결과: {form.resolution}",
            f"후속 조치: {form.follow_up}",
            f"후속 담당: {form.follow_up_owner}",
            f"후속 기한: {form.follow_up_due}",
        ]
    )
    return MaintenanceReport(
        report_id=row.report_id,
        incident_id=incident.incident_id,
        process_id=incident.process_id,
        asset_id=incident.asset_id,
        report_status=ReportStatus.SUBMITTED,
        report_version=version.version_no,
        data_origin=version.data_origin,
        incident=incident,
        ai_analysis=None
        if data["ai_analysis"] is None
        else AnalysisResult.model_validate(data["ai_analysis"]),
        maintenance=MaintenanceRecord(
            cause_category=form.cause_category or None,
            confirmed_cause=form.confirmed_cause,
            ai_assessment=form.ai_assessment,
            actions_taken=[]
            if form.action_status == "미수행"
            else [
                ActionTaken(
                    at=form.action_at,
                    action=form.actual_actions,
                    by=row.author_id,
                )
            ],
            parts_replaced=[
                p.strip()
                for p in form.replaced_parts.splitlines()
                if p.strip() and p.strip() != "없음"
            ],
            downtime=None
            if form.downtime_start is None
            else TimeRange(
                start=form.downtime_start,
                end=form.downtime_end,
                confirmed_by=row.author_id,
            ),
            test_run=TrialRun(
                result=form.trial_result, checked_window=form.trial_details
            ),
            remarks=remarks,
        ),
    )


def _new_report_id(session, error_code: str, timestamp) -> str:
    if not error_code or re.search(r"[:\s]", error_code):
        raise ValueError("에러 코드가 올바르지 않아 보고서 번호를 만들 수 없습니다.")
    prefix = f"RPT-{error_code}-{timestamp.astimezone(ZoneInfo('Asia/Seoul')):%Y%m%d}-"
    if session.bind.dialect.name == "postgresql":
        # 서로 다른 사건이라도 코드와 날짜가 같으면 같은 순번을 사용한다.
        lock_key = int.from_bytes(
            hashlib.blake2b(prefix.encode(), digest_size=8).digest(), "big", signed=True
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    existing = session.scalars(
        select(ReportRow.report_id).where(
            ReportRow.report_id.startswith(prefix, autoescape=True)
        )
    )
    deleted = session.scalars(
        select(DeletedReportNumberRow.report_id).where(
            DeletedReportNumberRow.report_id.startswith(prefix, autoescape=True)
        )
    )
    existing = list(existing) + list(deleted)
    sequences = [
        int(suffix) for value in existing if (suffix := value[len(prefix) :]).isdigit()
    ]
    report_id = f"{prefix}{max(sequences, default=0) + 1:03d}"
    if len(report_id) > 64:
        raise ValueError("에러 코드가 너무 길어 보고서 번호를 만들 수 없습니다.")
    return report_id


class SqlReports(Repository):
    def create_draft(self, actor_id: str, draft: ReportDraft) -> ReportDocument:
        with self._transaction() as session:
            user = _author(session, actor_id)
            if not draft.incident_id:
                raise ValueError("보고서를 저장하려면 사건을 선택하세요.")
            if self._engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            incident = session.scalar(
                select(IncidentRow)
                .where(IncidentRow.incident_id == draft.incident_id)
                .with_for_update()
            )
            if incident is None:
                raise UnknownIncidentError(draft.incident_id)
            if not incident.codes:
                raise ValueError("선택한 사건에 에러 코드가 없습니다.")
            snapshots = _snapshots(session, draft.incident_id)
            timestamp = now()
            row = ReportRow(
                report_id=_new_report_id(session, incident.codes[0], timestamp),
                author_id=actor_id,
                incident_id=draft.incident_id,
                report_status=ReportStatus.DRAFT,
                current_version=1,
                revision=1,
                data_origin=draft.data_origin,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(row)
            session.flush()
            version = ReportVersionRow(
                report_id=row.report_id,
                version_no=1,
                author_name=user.name,
                report_status=ReportStatus.DRAFT,
                data_origin=draft.data_origin,
                data={
                    **snapshots,
                    "form_data": draft.form_data.model_dump(mode="json"),
                    "report": None,
                },
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(version)
            session.flush()
            return _view(session, row, version)

    def save_draft(
        self,
        actor_id: str,
        report_id: str,
        draft: ReportDraft,
        *,
        expected_revision: int,
    ) -> ReportDocument:
        with self._transaction() as session:
            user = _author(session, actor_id)
            row, version = _load(session, report_id, lock=True)
            _owner(row, user)
            if row.report_status != ReportStatus.DRAFT:
                raise ReportConflictError("작성 중인 보고서만 수정할 수 있습니다.")
            if not draft.incident_id:
                raise ValueError("보고서를 저장하려면 사건을 선택하세요.")
            if row.incident_id is not None and row.incident_id != draft.incident_id:
                raise ReportConflictError(
                    "저장된 보고서의 연결 사건은 변경할 수 없습니다."
                )
            snapshots = (
                {k: deepcopy(version.data[k]) for k in ("incident", "ai_analysis")}
                if draft.incident_id == row.incident_id
                else _snapshots(session, draft.incident_id)
            )
            _claim(
                session,
                row,
                expected_revision,
                incident_id=draft.incident_id,
                data_origin=draft.data_origin,
            )
            version.data_origin = draft.data_origin
            version.data = {
                **snapshots,
                "form_data": draft.form_data.model_dump(mode="json"),
                "report": None,
            }
            version.updated_at = now()
            session.flush()
            return _view(session, row, version)

    def get_report(
        self, actor_id: str, report_id: str, *, version: int | None = None
    ) -> ReportDocument:
        with self._transaction() as session:
            _actor(session, actor_id)
            row, content = _load(session, report_id, version)
            return _view(session, row, content)

    def list_reports(
        self,
        actor_id: str,
        *,
        review: bool = False,
        all_reports: bool = False,
        approved_only: bool = False,
        limit: int = 100,
    ) -> list[ReportSummary]:
        if sum((review, all_reports, approved_only)) > 1:
            raise ValueError("보고서 조회 범위는 하나만 선택할 수 있습니다.")
        with self._transaction() as session:
            user = _actor(session, actor_id)
            if approved_only:
                latest_approved = (
                    select(
                        ReportVersionRow.report_id,
                        func.max(ReportVersionRow.version_no).label("version"),
                    )
                    .where(ReportVersionRow.report_status == ReportStatus.APPROVED)
                    .group_by(ReportVersionRow.report_id)
                    .subquery()
                )
                query = (
                    select(ReportRow, ReportVersionRow)
                    .join(
                        latest_approved,
                        latest_approved.c.report_id == ReportRow.report_id,
                    )
                    .join(
                        ReportVersionRow,
                        (ReportVersionRow.report_id == ReportRow.report_id)
                        & (ReportVersionRow.version_no == latest_approved.c.version),
                    )
                )
            else:
                query = select(ReportRow, ReportVersionRow).join(
                    ReportVersionRow,
                    (ReportVersionRow.report_id == ReportRow.report_id)
                    & (ReportVersionRow.version_no == ReportRow.current_version),
                )
            if review:
                statuses = {
                    Role.MAINT_LEAD.value: ReportStatus.SUBMITTED,
                    Role.CONTROL.value: ReportStatus.REVIEWED,
                }
                if user.role not in statuses:
                    raise ReportForbiddenError(
                        "결재 직책만 결재 대기 목록을 조회할 수 있습니다."
                    )
                query = query.where(
                    ReportRow.report_status == statuses[user.role],
                    ReportRow.author_id != actor_id,
                )
            elif not approved_only and not all_reports:
                query = query.where(ReportRow.author_id == actor_id)
            return [
                ReportSummary(
                    report_id=r.report_id,
                    author_id=r.author_id,
                    author_name=v.author_name,
                    report_version=v.version_no,
                    report_status=v.report_status,
                    incident_id=(v.data["incident"] or {}).get("incident_id"),
                    asset_id=(v.data["incident"] or {}).get("asset_id"),
                    updated_at=utc(v.updated_at if approved_only else r.updated_at),
                )
                for r, v in session.execute(
                    query.order_by(
                        ReportRow.updated_at.desc(), ReportRow.report_id
                    ).limit(min(max(limit, 1), 200))
                )
            ]

    def review_history(
        self, actor_id: str, *, limit: int = 100
    ) -> list[ReportReviewHistory]:
        with self._transaction() as session:
            user = _actor(session, actor_id)
            if user.role not in (Role.MAINT_LEAD.value, Role.CONTROL.value):
                raise ReportForbiddenError(
                    "결재 직책만 내 결재 이력을 조회할 수 있습니다."
                )
            ranked = (
                select(
                    ApprovalRow.id.label("approval_id"),
                    func.row_number()
                    .over(
                        partition_by=ApprovalRow.report_id,
                        order_by=(ApprovalRow.at.desc(), ApprovalRow.id.desc()),
                    )
                    .label("rank"),
                )
                .where(
                    ApprovalRow.employee_no == actor_id,
                    ApprovalRow.decision.in_(("승인", "반려")),
                )
                .subquery()
            )
            query = (
                select(ApprovalRow, ReportRow, ReportVersionRow)
                .join(
                    ranked,
                    (ranked.c.approval_id == ApprovalRow.id) & (ranked.c.rank == 1),
                )
                .join(ReportRow, ReportRow.report_id == ApprovalRow.report_id)
                .join(
                    ReportVersionRow,
                    (ReportVersionRow.report_id == ReportRow.report_id)
                    & (ReportVersionRow.version_no == ReportRow.current_version),
                )
                .order_by(ApprovalRow.at.desc(), ApprovalRow.id.desc())
                .limit(min(max(limit, 1), 200))
            )
            return [
                ReportReviewHistory(
                    report=ReportSummary(
                        report_id=row.report_id,
                        author_id=row.author_id,
                        author_name=version.author_name,
                        report_version=row.current_version,
                        report_status=row.report_status,
                        incident_id=row.incident_id,
                        asset_id=(version.data["incident"] or {}).get("asset_id"),
                        updated_at=utc(row.updated_at),
                    ),
                    review_version=approval.version_no,
                    review_step=approval.step,
                    review_role=approval.role,
                    decision=approval.decision,
                    reviewed_at=utc(approval.at),
                )
                for approval, row, version in session.execute(query)
            ]

    def transition(
        self,
        actor_id: str,
        report_id: str,
        action: str,
        *,
        expected_revision: int,
        comment: str = "",
    ) -> ReportDocument:
        with self._transaction() as session:
            user = _actor(session, actor_id)
            row, version = _load(session, report_id, lock=True)
            if action == "submit":
                _owner(row, user)
                required, source, target, step = (
                    None,
                    ReportStatus.DRAFT,
                    ReportStatus.REVIEWED
                    if user.role == Role.MAINT_LEAD.value
                    else ReportStatus.SUBMITTED,
                    1,
                )
                _author(session, actor_id)
                report = _submitted_report(row, version)
            elif action == "review":
                required, source, target, step = (
                    Role.MAINT_LEAD,
                    ReportStatus.SUBMITTED,
                    ReportStatus.REVIEWED,
                    2,
                )
                report = None
            elif action == "approve":
                required, source, target, step = (
                    Role.CONTROL,
                    ReportStatus.REVIEWED,
                    ReportStatus.APPROVED,
                    3,
                )
                report = None
            elif action == "reject":
                source = row.report_status
                if source not in (ReportStatus.SUBMITTED, ReportStatus.REVIEWED):
                    raise ReportConflictError(
                        "제출·검토 중인 보고서만 반려할 수 있습니다."
                    )
                required = (
                    Role.MAINT_LEAD
                    if source == ReportStatus.SUBMITTED
                    else Role.CONTROL
                )
                target, step = (
                    ReportStatus.REJECTED,
                    2 if source == ReportStatus.SUBMITTED else 3,
                )
                if not comment.strip():
                    raise ValueError("반려 사유를 입력하세요.")
                report = None
            else:
                raise ValueError("지원하지 않는 보고서 작업입니다.")
            if (required is not None and user.role != required.value) or (
                action != "submit" and actor_id == row.author_id
            ):
                raise ReportForbiddenError(
                    "해당 결재 직책이어야 하며 본인 보고서를 결재할 수 없습니다."
                )
            if row.report_status != source:
                raise ReportConflictError(
                    "현재 상태에서 실행할 수 없습니다. 다시 불러오세요."
                )
            _claim(session, row, expected_revision, report_status=target)
            data = deepcopy(version.data)
            report = report or MaintenanceReport.model_validate(data["report"])
            session.add(
                ApprovalRow(
                    report_id=row.report_id,
                    version_no=version.version_no,
                    step=step,
                    employee_no=actor_id,
                    role=user.role,
                    decision="제출"
                    if action == "submit"
                    else "반려"
                    if action == "reject"
                    else "승인",
                    comment=comment.strip() or None,
                    at=now(),
                )
            )
            session.flush()
            report.report_status = target
            report.approval = _approvals(session, version)
            data["report"] = report.model_dump(mode="json")
            version.data, version.report_status, version.updated_at = (
                data,
                target,
                now(),
            )
            if target == ReportStatus.APPROVED:
                session.add(
                    ReportIndexJobRow(
                        report_id=row.report_id,
                        version_no=version.version_no,
                        status="pending",
                        created_at=now(),
                    )
                )
            session.flush()
            return _view(session, row, version)

    def revise(
        self, actor_id: str, report_id: str, *, expected_revision: int
    ) -> ReportDocument:
        with self._transaction() as session:
            user = _author(session, actor_id)
            row, previous = _load(session, report_id, lock=True)
            _owner(row, user)
            if row.report_status != ReportStatus.REJECTED:
                raise ReportConflictError(
                    "반려된 보고서에서만 개정판을 만들 수 있습니다."
                )
            _claim(
                session,
                row,
                expected_revision,
                current_version=row.current_version + 1,
                report_status=ReportStatus.DRAFT,
            )
            data = deepcopy(previous.data)
            data["report"] = None
            version = ReportVersionRow(
                report_id=report_id,
                version_no=row.current_version,
                author_name=user.name,
                report_status=ReportStatus.DRAFT,
                data_origin=previous.data_origin,
                data=data,
                created_at=now(),
                updated_at=now(),
            )
            session.add(version)
            session.flush()
            return _view(session, row, version)

    def delete_draft(
        self, actor_id: str, report_id: str, *, expected_revision: int
    ) -> ReportDocument | None:
        with self._transaction() as session:
            if self._engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            user = _author(session, actor_id)
            row, version = _load(session, report_id, lock=True)
            _owner(row, user)
            if row.report_status != ReportStatus.DRAFT:
                raise ReportConflictError(
                    "작성 중인 보고서만 삭제하거나 수정을 취소할 수 있습니다."
                )
            if row.revision != expected_revision:
                raise ReportConflictError(
                    "다른 작업으로 보고서가 변경됐습니다. 다시 불러오세요."
                )
            if row.current_version == 1:
                session.add(DeletedReportNumberRow(report_id=report_id))
                session.delete(version)
                session.flush()
                session.delete(row)
                return None
            previous = session.get(
                ReportVersionRow, (report_id, row.current_version - 1)
            )
            if previous is None or previous.report_status != ReportStatus.REJECTED:
                raise ReportConflictError("이전 반려 보고서를 찾을 수 없습니다.")
            session.delete(version)
            session.flush()
            _claim(
                session,
                row,
                expected_revision,
                current_version=previous.version_no,
                report_status=ReportStatus.REJECTED,
                incident_id=(previous.data["incident"] or {}).get("incident_id"),
                data_origin=previous.data_origin,
            )
            return _view(session, row, previous)

    def delete_approved(
        self,
        actor_id: str,
        report_id: str,
        *,
        expected_revision: int,
        delete_vector: Callable[[str], int],
    ) -> int:
        with self._transaction() as session:
            if self._engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            _actor(session, actor_id, Role.CONTROL)
            row, _ = _load(session, report_id, lock=True)
            if row.report_status != ReportStatus.APPROVED:
                raise ReportConflictError("최종 승인된 보고서만 삭제할 수 있습니다.")
            if row.revision != expected_revision:
                raise ReportConflictError(
                    "다른 작업으로 보고서가 변경됐습니다. 다시 불러오세요."
                )
            removed = delete_vector(report_id)
            session.add(DeletedReportNumberRow(report_id=report_id))
            for model in (ReportIndexJobRow, ApprovalRow, ReportVersionRow):
                session.execute(delete(model).where(model.report_id == report_id))
            session.delete(row)
            return removed

    def approved_reports(self) -> list[MaintenanceReport]:
        """보고서별 최신 승인 판 전체. 현재 초안과 색인 작업 상태에 영향받지 않는다.

        유사 검색의 top-k와 구분한 구조화 조회용이다. 호출자가 사람 작성 칸만 투영한다.
        """
        # 전체 중 가장 최근 보고서 하나가 아니라, 각 report_id별 가장 높은 승인 버전을 고른다.
        # 승인 판 뒤에 초안·반려 개정판이 생겨도 기존 승인 판은 검색 대상으로 남는다.
        latest = (
            select(
                ReportVersionRow.report_id,
                func.max(ReportVersionRow.version_no).label("version"),
            )
            .where(ReportVersionRow.report_status == ReportStatus.APPROVED)
            .group_by(ReportVersionRow.report_id)
            .subquery()
        )
        with self._transaction() as session:
            rows = session.scalars(
                select(ReportVersionRow)
                .join(
                    latest,
                    (ReportVersionRow.report_id == latest.c.report_id)
                    & (ReportVersionRow.version_no == latest.c.version),
                )
                .order_by(ReportVersionRow.report_id)
            )
            return [
                MaintenanceReport.model_validate(row.data["report"]) for row in rows
            ]

    def pending_index_reports(
        self,
        *,
        limit: int = 100,
        include_failed: bool = False,
        exclude_report_ids: frozenset[str] = frozenset(),
    ) -> list[MaintenanceReport]:
        """보고서별 최신 승인 판의 대기 작업만 반환한다(실패 판은 명시적 재시도)."""
        latest = (
            select(
                ReportVersionRow.report_id,
                func.max(ReportVersionRow.version_no).label("version"),
            )
            .where(ReportVersionRow.report_status == ReportStatus.APPROVED)
            .group_by(ReportVersionRow.report_id)
            .subquery()
        )
        with self._transaction() as session:
            query = (
                select(ReportVersionRow)
                .join(
                    latest,
                    (ReportVersionRow.report_id == latest.c.report_id)
                    & (ReportVersionRow.version_no == latest.c.version),
                )
                .join(
                    ReportIndexJobRow,
                    (ReportIndexJobRow.report_id == ReportVersionRow.report_id)
                    & (ReportIndexJobRow.version_no == ReportVersionRow.version_no),
                )
                .where(
                    ReportIndexJobRow.status.in_(
                        ["pending", "failed"] if include_failed else ["pending"]
                    )
                )
                .order_by(ReportIndexJobRow.created_at, ReportIndexJobRow.report_id)
                .limit(min(max(limit, 1), 200))
            )
            if exclude_report_ids:
                query = query.where(
                    ReportIndexJobRow.report_id.not_in(exclude_report_ids)
                )
            return [
                MaintenanceReport.model_validate(v.data["report"])
                for v in session.scalars(query)
            ]

    @contextmanager
    def locked_index_job(
        self, report_id: str, *, include_failed: bool = False
    ) -> Iterator[ReportIndexWork | None]:
        """보고서별로 승인·벡터 쓰기를 직렬화한다(외부 프로세스도 같은 DB 잠금)."""
        with self._transaction() as session:
            if self._engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            row = session.scalar(
                select(ReportRow)
                .where(ReportRow.report_id == report_id)
                .with_for_update()
            )
            if row is None:
                yield None
                return
            version = session.scalar(
                select(ReportVersionRow)
                .where(
                    ReportVersionRow.report_id == report_id,
                    ReportVersionRow.report_status == ReportStatus.APPROVED,
                )
                .order_by(ReportVersionRow.version_no.desc())
                .limit(1)
            )
            if version is None:
                yield None
                return
            job = session.get(ReportIndexJobRow, (report_id, version.version_no))
            allowed = ("pending", "failed") if include_failed else ("pending",)
            if job is None or job.status not in allowed:
                yield None
                return

            def finish(success: bool) -> None:
                job.status = "indexed" if success else "failed"
                session.flush()

            yield ReportIndexWork(
                report=MaintenanceReport.model_validate(version.data["report"]),
                finish=finish,
            )

    def record_index_result(
        self, report_id: str, version: int, *, success: bool
    ) -> None:
        """벡터 저장 뒤 결과를 기록한다. 재실행 성공은 멱등적으로 처리한다."""
        with self._transaction() as session:
            job = session.scalar(
                select(ReportIndexJobRow)
                .where(
                    ReportIndexJobRow.report_id == report_id,
                    ReportIndexJobRow.version_no == version,
                )
                .with_for_update()
            )
            if job is None:
                raise ReportNotFoundError("검색 등록 작업을 찾을 수 없습니다.")
            if job.status == "indexed":
                return
            if job.status not in ("pending", "failed"):
                raise ReportConflictError("이미 완료된 검색 등록 작업입니다.")
            job.status = "indexed" if success else "failed"
