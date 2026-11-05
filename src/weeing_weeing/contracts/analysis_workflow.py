"""사건 분석 단계별 공개 결과. 내부 대화 대신 근거와 검증 지적을 전달한다."""

from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from weeing_weeing.contracts.analysis import (
    AnalysisResult,
    Evidence,
    MaintenanceReference,
    validate_reference_sources,
)

AnalysisRole = Literal["documents", "reports", "synthesis", "verification"]


class ResearchFinding(BaseModel):
    statement: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class ResearchResult(BaseModel):
    findings: list[ResearchFinding] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    reference_cases: list[MaintenanceReference] = Field(
        default_factory=list, max_length=2
    )


class VerificationIssue(BaseModel):
    claim: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    correction: str = Field(min_length=1, max_length=2000)


class VerificationResult(BaseModel):
    verdict: Literal["PASS", "REVISE", "INSUFFICIENT_EVIDENCE"]
    summary: str = Field(min_length=1, max_length=2000)
    issues: list[VerificationIssue] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.verdict == "PASS" and self.issues:
            raise ValueError("검증 통과에는 미해결 지적을 넣을 수 없습니다")
        if self.verdict == "REVISE" and not self.issues:
            raise ValueError("수정 요청에는 구체적인 지적이 필요합니다")
        return self


class AnalysisAgentRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: AnalysisRole
    attempt: int = Field(default=1, ge=1, le=2)
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "SKIPPED"]
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    model: str | None = None
    prompt_version: str | None = None
    calls: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    evidence: list[Evidence] = Field(default_factory=list)
    sensor_windows: dict[str, dict] = Field(default_factory=dict)
    research: ResearchResult | None = None
    analysis: AnalysisResult | None = None
    verification: VerificationResult | None = None
    summary: str = ""
    error_code: str | None = None
    reused_from_job_id: str | None = Field(default=None, min_length=32, max_length=32)

    @model_validator(mode="after")
    def citations(self) -> Self:
        known = {item.evidence_id for item in self.evidence}
        cited = set()
        if self.research:
            if self.role != "reports" and self.research.reference_cases:
                raise ValueError("참고 사례는 정비이력 조사에서만 제출합니다")
            validate_reference_sources(self.research.reference_cases, self.evidence)
            cited.update(i for f in self.research.findings for i in f.evidence_ids)
        if self.verification:
            cited.update(i for f in self.verification.issues for i in f.evidence_ids)
        if not cited <= known:
            raise ValueError("단계 결과가 확보하지 않은 근거를 인용했습니다")
        if self.finished_at and self.started_at and self.finished_at < self.started_at:
            raise ValueError("종료 시각이 시작 시각보다 빠릅니다")
        return self


class AnalysisCheckpoint(BaseModel):
    """서버가 저장한 단계 경계. LLM 대화가 아닌 재실행 입력만 보존한다."""

    model_config = ConfigDict(extra="forbid")
    version: Literal["multi-analysis-v1"] = "multi-analysis-v1"
    incident_id: str
    verification_enabled: bool
    runs: list[AnalysisAgentRun] = Field(default_factory=list, max_length=6)
    sensor_windows: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_steps(self) -> Self:
        keys = [(run.role, run.attempt) for run in self.runs]
        if len(keys) != len(set(keys)):
            raise ValueError("체크포인트 단계가 중복되었습니다")
        for run in self.runs:
            if run.status != "COMPLETED":
                continue
            result = (
                run.research
                if run.role in ("documents", "reports")
                else run.analysis
                if run.role == "synthesis"
                else run.verification
            )
            if result is None:
                raise ValueError("완료 단계의 재개 입력이 없습니다")
            if run.analysis and run.analysis.incident_id != self.incident_id:
                raise ValueError("체크포인트 사건 ID 불일치")
        return self
