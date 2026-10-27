"""보고서 저장·결재(#62). 권한·상태·revision 검사와 기록은 같은 트랜잭션에서 처리한다."""

from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select, update

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


def _actor(session, employee_no: str, role: Role | None = None) -> UserRow:
    user = session.get(UserRow, employee_no)
    if user is None or not user.is_active or (role and user.role != role.value):
        raise ReportForbiddenError("이 작업을 할 수 있는 활성 계정이 아닙니다.")
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


def _readable(row: ReportRow, version: ReportVersionRow, user: UserRow) -> None:
    if row.author_id == user.employee_no:
        return
    if user.role in (Role.MAINT_LEAD.value, Role.CONTROL.value) and (
        version.report_status != ReportStatus.DRAFT
    ):
        return
    raise ReportForbiddenError("이 보고서를 조회할 수 없습니다.")


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


class SqlReports(Repository):
    def create_draft(self, actor_id: str, draft: ReportDraft) -> ReportDocument:
        with self._transaction() as session:
            user = _actor(session, actor_id, Role.INSPECTOR)
            snapshots = _snapshots(session, draft.incident_id)
            timestamp = now()
            row = ReportRow(
                report_id=f"RPT-{uuid4().hex}",
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
            user = _actor(session, actor_id, Role.INSPECTOR)
            row, version = _load(session, report_id, lock=True)
            _owner(row, user)
            if row.report_status != ReportStatus.DRAFT:
                raise ReportConflictError("작성 중인 보고서만 수정할 수 있습니다.")
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
            user = _actor(session, actor_id)
            row, content = _load(session, report_id, version)
            _readable(row, content, user)
            return _view(session, row, content)

    def list_reports(
        self, actor_id: str, *, review: bool = False, limit: int = 100
    ) -> list[ReportSummary]:
        with self._transaction() as session:
            user = _actor(session, actor_id)
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
            else:
                query = query.where(ReportRow.author_id == actor_id)
            return [
                ReportSummary(
                    report_id=r.report_id,
                    author_id=r.author_id,
                    author_name=v.author_name,
                    report_version=r.current_version,
                    report_status=r.report_status,
                    incident_id=r.incident_id,
                    asset_id=(v.data["incident"] or {}).get("asset_id"),
                    updated_at=utc(r.updated_at),
                )
                for r, v in session.execute(
                    query.order_by(
                        ReportRow.updated_at.desc(), ReportRow.report_id
                    ).limit(min(max(limit, 1), 200))
                )
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
                    Role.INSPECTOR,
                    ReportStatus.DRAFT,
                    ReportStatus.SUBMITTED,
                    1,
                )
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
            if user.role != required.value or (
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
                    role=required.value,
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
            user = _actor(session, actor_id, Role.INSPECTOR)
            row, previous = _load(session, report_id, lock=True)
            _owner(row, user)
            if row.report_status not in (ReportStatus.REJECTED, ReportStatus.APPROVED):
                raise ReportConflictError(
                    "반려·승인된 보고서에서만 개정판을 만들 수 있습니다."
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

    def pending_index_reports(self, *, limit: int = 100) -> list[MaintenanceReport]:
        """#29의 소비 지점. 보고서별 가장 최근 승인 판만 반환한다(이전 승인 판은 보존)."""
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
                .where(ReportIndexJobRow.status == "pending")
                .order_by(ReportIndexJobRow.created_at, ReportIndexJobRow.report_id)
                .limit(min(max(limit, 1), 200))
            )
            return [
                MaintenanceReport.model_validate(v.data["report"])
                for v in session.scalars(query)
            ]
