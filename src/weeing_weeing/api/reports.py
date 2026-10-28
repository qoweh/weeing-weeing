"""로그인한 작성자의 보고서와 직책별 결재 API(#62)."""

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from weeing_weeing.api.auth import CurrentUser
from weeing_weeing.api.report_index import run_pending_reports
from weeing_weeing.contracts import Incident, ReportDocument, ReportDraft, ReportSummary
from weeing_weeing.db import interface as db

router = APIRouter(tags=["reports"])


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
    user: CurrentUser, limit: int = Query(default=100, ge=1, le=200)
) -> list[Incident]:
    """보고서에서 연결할 실제 저장 사건. 입력값으로 사건·AI 스냅샷을 받지 않는다."""
    return db.get_incidents().list_incidents(limit=limit)


@router.post("/reports", status_code=201)
def create_report(
    body: ReportDraft, user: CurrentUser, repo: Reports
) -> ReportDocument:
    return _call(repo.create_draft, user.employee_no, body)


@router.get("/reports")
def list_reports(
    user: CurrentUser,
    repo: Reports,
    scope: Literal["mine", "review"] = "mine",
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ReportSummary]:
    return _call(
        repo.list_reports, user.employee_no, review=scope == "review", limit=limit
    )


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
