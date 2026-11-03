"""보고서 초안·조회 계약(#62). 미완성 초안과 제출된 MaintenanceReport를 구분한다."""

from datetime import date
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from weeing_weeing.contracts.analysis import AnalysisResult
from weeing_weeing.contracts.incident import Incident
from weeing_weeing.contracts.report import ApprovalStep, MaintenanceReport, ReportStatus

DataOrigin = Literal["LIVE", "REPLAY", "SYNTHETIC"]


class ReportFormData(BaseModel):
    """사람이 입력한 폼. 빈 칸은 초안에서 허용하고 제출 때 필수 항목을 검사한다."""

    model_config = ConfigDict(extra="forbid", str_max_length=10_000)

    department: str = ""
    process_impact: Literal["미확인", "정지", "감속", "영향 없음"] = "미확인"
    actual_actions: str = ""
    action_status: Literal["수행", "미수행"] = "수행"
    replaced_parts: str = ""
    action_at: AwareDatetime | None = None
    cause_category: str = ""
    confirmed_cause: str = ""
    cause_evidence: str = ""
    ai_assessment: Literal["일치", "부분 일치", "불일치", "판단 불가"] = "판단 불가"
    trial_result: Literal["미실시", "정상", "부적합"] = "미실시"
    trial_details: str = ""
    downtime_start: AwareDatetime | None = None
    downtime_end: AwareDatetime | None = None
    resolution: Literal["미확인", "해결", "미해결", "보류"] = "미확인"
    follow_up: str = ""
    follow_up_owner: str = ""
    follow_up_due: str = Field(default="", pattern=r"^(?:\d{4}-\d{2}-\d{2})?$")

    @field_validator("follow_up_due")
    @classmethod
    def _valid_date(cls, value: str) -> str:
        if value:
            date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def _time_order(self) -> Self:
        if (
            self.downtime_start is not None
            and self.downtime_end is not None
            and self.downtime_end < self.downtime_start
        ):
            raise ValueError("운전 복귀 시각은 정지 시작 이후여야 합니다.")
        return self


class ReportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str | None = Field(default=None, min_length=1, max_length=64)
    data_origin: DataOrigin = "LIVE"
    form_data: ReportFormData = Field(default_factory=ReportFormData)


class ReportDocument(BaseModel):
    """한 버전의 조회 결과. revision은 보고서 전체의 낙관적 잠금 번호다."""

    report_id: str
    author_id: str
    author_name: str
    report_version: int
    current_version: int
    report_status: ReportStatus
    revision: int
    data_origin: DataOrigin
    incident_id: str | None
    incident: Incident | None
    ai_analysis: AnalysisResult | None
    form_data: ReportFormData
    approval: list[ApprovalStep]
    report: MaintenanceReport | None
    index_status: Literal["pending", "indexed", "failed"] | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ReportSummary(BaseModel):
    report_id: str
    author_id: str
    author_name: str
    report_version: int
    report_status: ReportStatus
    incident_id: str | None
    asset_id: str | None
    updated_at: AwareDatetime
