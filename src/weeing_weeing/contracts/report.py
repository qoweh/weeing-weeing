"""정비 보고서와 결재 계약.

출처: 노션 '김민우 (정리본)' 4장 정비 보고서 규격 v1.0 초안과 예시 JSON,
정비 보고서 양식 v1.2(CONV-MR-S-001).

칸마다 쓰는 주체가 정해져 있다.
- incident: 시스템 / ai_analysis: AI / maintenance: 현장 점검자 / approval: 결재자
AI는 maintenance·approval을 쓰지 않는다. RAG에는 승인된 보고서의 사람 작성 칸만 넣는다.
"""

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from weeing_weeing.contracts.analysis import AnalysisResult
from weeing_weeing.contracts.incident import Incident


class Role(StrEnum):
    """직책 4종 (10/16 회의 피드백)."""

    CONTROL = "관제 담당자"
    MAINT_LEAD = "보전 팀장"
    SITE_MANAGER = "현장 책임자"
    INSPECTOR = "현장 점검자"


class ReportStatus(StrEnum):
    DRAFT = "DRAFT"  # AI 초안 또는 작성 중
    SUBMITTED = "SUBMITTED"  # 현장 점검자 제출
    REVIEWED = "REVIEWED"  # 보전 팀장 승인
    APPROVED = "APPROVED"  # 관제 담당자 승인 = 확정
    REJECTED = "REJECTED"


class ActionTaken(BaseModel):
    at: AwareDatetime
    action: str
    by: str  # 사번


class TimeRange(BaseModel):
    start: AwareDatetime
    end: AwareDatetime | None = None
    confirmed_by: str | None = None


class TrialRun(BaseModel):
    result: Literal["정상", "부적합", "미실시"]
    checked_window: str | None = None


class Photo(BaseModel):
    tag: Literal["before", "after"]
    caption: str
    file: str  # 저장 경로 또는 파일 ID


class MaintenanceRecord(BaseModel):
    """현장 점검자가 쓰는 실제 정비 결과."""

    cause_category: str | None = None
    confirmed_cause: str | None = None  # 미확인이면 None
    ai_assessment: Literal["일치", "부분 일치", "불일치", "판단 불가"] | None = None
    actions_taken: list[ActionTaken] = Field(default_factory=list)
    parts_replaced: list[str] = Field(default_factory=list)
    isolation: TimeRange | None = None  # LOTO 격리 구간
    downtime: TimeRange | None = None  # 정지시간(알람 지속시간과 다름)
    vendor: str | None = None  # 외부 업체 의뢰 시
    test_run: TrialRun | None = None  # 재가동 시험운전
    photos: list[Photo] = Field(default_factory=list)
    remarks: str = ""


class ApprovalStep(BaseModel):
    step: int
    role: Role
    user: str
    decision: Literal["제출", "승인", "반려"]
    comment: str | None = None
    at: AwareDatetime


class MaintenanceReport(BaseModel):
    report_id: str  # 예: RPT-20261005-001
    incident_id: str
    process_id: str
    asset_id: str
    report_status: ReportStatus = ReportStatus.DRAFT
    report_version: int = 1
    data_origin: Literal["LIVE", "REPLAY", "SYNTHETIC"]
    incident: Incident
    ai_analysis: AnalysisResult | None = None
    maintenance: MaintenanceRecord | None = None
    approval: list[ApprovalStep] = Field(default_factory=list)
