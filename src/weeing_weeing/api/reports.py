"""로그인 사용자 공통 보고서 조회와 작성자 수정·직책별 결재 API(#62)."""

import logging
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from weeing_weeing.api.auth import CurrentUser
from weeing_weeing.api.report_index import run_pending_reports
from weeing_weeing.contracts import (
    Incident,
    ReportDocument,
    ReportDraft,
    ReportSummary,
    Role,
)
from weeing_weeing.db import interface as db
from weeing_weeing.rag import interface as rag

router = APIRouter(tags=["reports"])
logger = logging.getLogger(__name__)


def reports() -> db.ReportRepository:
    return db.get_reports()


Reports = Annotated[db.ReportRepository, Depends(reports)]


class SaveDraft(ReportDraft):
    expected_revision: int = Field(ge=1)


class ReportAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    comment: str = Field(default="", max_length=2000)


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except db.ReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except db.UnknownIncidentError as exc:
        raise HTTPException(
            status_code=422, detail="저장된 사건을 선택하세요."
        ) from exc
    except db.ReportForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except db.ReportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/incidents")
def list_incidents(
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Incident]:
    """보고서에서 연결할 실제 저장 사건. 입력값으로 사건·AI 스냅샷을 받지 않는다."""
    return db.get_incidents().list_incidents(limit=limit, offset=offset)


@router.get("/incidents/overview")
def incident_overview(
    user: CurrentUser,
    repo: Reports,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """Error 사건과 보고서 승인 여부를 함께 조회한다."""
    return _call(repo.incident_overview, user.employee_no, limit=limit, offset=offset)


@router.get("/incidents/{incident_id}/approved-reports")
def incident_approved_reports(
    incident_id: str, user: CurrentUser, repo: Reports
) -> list[ReportSummary]:
    """로그인한 사용자가 해당 사건의 승인 보고서를 조회한다."""
    if db.get_incidents().get_incident(incident_id) is None:
        raise HTTPException(status_code=404, detail="저장된 사건이 없습니다.")
    return _call(repo.incident_approved_reports, user.employee_no, incident_id)


def _delete_report_vector(doc_id: str) -> int:
    try:
        return rag.get_indexer().delete_report(doc_id)
    except Exception as exc:
        logger.error("보고서 검색 자료 삭제 실패: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="검색 자료 삭제에 실패했습니다. 다시 시도해 주세요.",
        ) from exc


@router.delete("/incidents/{incident_id}")
def delete_incident(incident_id: str, user: CurrentUser, repo: Reports) -> dict:
    """관제 담당자가 사건과 연결 보고서·분석·검색 자료를 삭제한다."""
    try:
        result = repo.delete_incident(
            user.employee_no, incident_id, delete_vector=_delete_report_vector
        )
    except db.UnknownIncidentError as exc:
        raise HTTPException(status_code=404, detail="저장된 사건이 없습니다.") from exc
    except db.ReportForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except db.ReportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "deleted", **result}


@router.get("/incidents/{incident_id}/report-context")
def incident_report_context(
    incident_id: str, user: CurrentUser, repo: Reports, report_id: str | None = None
) -> dict:
    """보고서 분석의 실제 입력 시각에 대응하는 DB 표본을 읽기만 한다."""
    incident = db.get_incidents().get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="저장된 사건이 없습니다.")
    draft = (
        _call(repo.find_incident_draft, user.employee_no, incident_id)
        if user.role in (Role.INSPECTOR, Role.MAINT_LEAD)
        else None
    )
    document = (
        _call(repo.get_report, user.employee_no, report_id) if report_id else draft
    )
    if document and document.incident_id != incident_id:
        raise HTTPException(409, "보고서와 사건이 일치하지 않습니다.")
    jobs = db.get_analysis_jobs()
    analysis = (
        document.ai_analysis
        if document and document.ai_analysis is not None
        else jobs.latest_analysis(incident_id)
    )
    analysis_incident = jobs.analysis_input(analysis) if analysis else None
    notes = []
    if analysis_incident and (
        analysis_incident.incident_id != incident_id
        or analysis_incident.process_id != incident.process_id
        or analysis_incident.asset_id != incident.asset_id
    ):
        raise HTTPException(409, "분석 입력과 사건의 설비가 일치하지 않습니다.")
    anchor = (
        analysis_incident.last_detected_at
        if analysis_incident
        else None
        if analysis
        else incident.confirmed_at or incident.first_detected_at
    )
    if analysis and analysis_incident is None:
        notes.append(
            "분석 입력 스냅샷이 없어 분석 시점의 센서 표본을 확인할 수 없습니다."
        )
    rows = (
        db.get_telemetry().between(
            incident.asset_id,
            anchor - timedelta(seconds=2),
            anchor + timedelta(microseconds=1),
            process_id=incident.process_id,
            limit=100,
        )
        if anchor
        else []
    )
    if anchor and not rows:
        notes.append("기준 시각 이전 2초 이내에 저장된 센서 표본이 없습니다.")
    elif rows and rows[-1].timestamp != anchor:
        notes.append("기준 시각의 정확한 표본이 없어 이전 2초 이내 표본을 표시합니다.")
    return {
        "incident": incident,
        "draft": draft,
        "document": document,
        "telemetry": rows[-1] if rows else None,
        "analysis": analysis,
        "analysis_incident": analysis_incident,
        "telemetry_anchor": anchor,
        "telemetry_notes": notes,
    }


@router.post("/reports", status_code=201)
def create_report(
    body: ReportDraft, user: CurrentUser, repo: Reports
) -> ReportDocument:
    return _call(repo.create_draft, user.employee_no, body)


@router.get("/reports")
def list_reports(
    user: CurrentUser,
    repo: Reports,
    scope: Literal["mine", "review", "all", "approved"] = "mine",
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
) -> list[ReportSummary]:
    return _call(
        repo.list_reports,
        user.employee_no,
        review=scope == "review",
        all_reports=scope == "all",
        approved_only=scope == "approved",
        limit=limit,
        offset=offset,
    )


@router.get("/reports/review-history")
def review_history(
    user: CurrentUser,
    repo: Reports,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[db.ReportReviewHistory]:
    return _call(repo.review_history, user.employee_no, limit=limit, offset=offset)


@router.get("/reports/{report_id}")
def get_report(report_id: str, user: CurrentUser, repo: Reports) -> ReportDocument:
    return _call(repo.get_report, user.employee_no, report_id)


@router.get("/reports/{report_id}/versions/{version}")
def get_version(
    report_id: str, version: int, user: CurrentUser, repo: Reports
) -> ReportDocument:
    return _call(repo.get_report, user.employee_no, report_id, version=version)


@router.put("/reports/{report_id}/draft")
def save_draft(
    report_id: str, body: SaveDraft, user: CurrentUser, repo: Reports
) -> ReportDocument:
    draft = ReportDraft.model_validate(body.model_dump(exclude={"expected_revision"}))
    return _call(
        repo.save_draft,
        user.employee_no,
        report_id,
        draft,
        expected_revision=body.expected_revision,
    )


@router.delete("/reports/{report_id}/draft")
def delete_draft(report_id: str, body: ReportAction, user: CurrentUser, repo: Reports):
    restored = _call(
        repo.delete_draft,
        user.employee_no,
        report_id,
        expected_revision=body.expected_revision,
    )
    return {"status": "restored" if restored else "deleted", "report": restored}


@router.delete("/reports/{report_id}")
def delete_approved_report(
    report_id: str, body: ReportAction, user: CurrentUser, repo: Reports
):
    removed = _call(
        repo.delete_approved,
        user.employee_no,
        report_id,
        expected_revision=body.expected_revision,
        delete_vector=_delete_report_vector,
    )
    return {"status": "deleted", "removed_chunks": removed}


@router.post("/reports/{report_id}/revise", status_code=201)
def revise_report(
    report_id: str, body: ReportAction, user: CurrentUser, repo: Reports
) -> ReportDocument:
    return _call(
        repo.revise,
        user.employee_no,
        report_id,
        expected_revision=body.expected_revision,
    )


@router.post("/reports/{report_id}/{action}")
def transition(
    report_id: str,
    action: Literal["submit", "review", "approve", "reject"],
    body: ReportAction,
    user: CurrentUser,
    repo: Reports,
    background_tasks: BackgroundTasks,
) -> ReportDocument:
    result = _call(
        repo.transition,
        user.employee_no,
        report_id,
        action,
        expected_revision=body.expected_revision,
        comment=body.comment,
    )
    if action == "approve":
        background_tasks.add_task(run_pending_reports)
    return result
