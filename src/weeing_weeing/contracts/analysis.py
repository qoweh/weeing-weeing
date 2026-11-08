"""RAG 검색 근거(Evidence)와 AI 분석 결과(AnalysisResult) 계약.

출처: 1차 분담 'AI Agent 개발 4. 결과 구조화 및 검증', 노션 '김민우 (정리본)' 보고서 예시의
ai_analysis 칸. AI는 제안까지만 하고 원인 확정·재가동은 사람이 한다.
"""

from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator

Likelihood = Literal["상", "중", "하", "미평가"]  # 과거 저장 결과 호환용
InspectionPriority = Literal["우선 확인", "후속 확인"]


class ReportActionTiming(BaseModel):
    """서버가 시간대를 정규화해 계산한 보고서 조치와 현재 사건의 시간 차이."""

    action_index: int = Field(ge=0)
    action_at: AwareDatetime
    incident_at: AwareDatetime
    offset_seconds: float = Field(allow_inf_nan=False)  # 조치 - 현재 사건 최초 감지


class CheckCitation(BaseModel):
    check_index: int = Field(ge=0)  # recommended_checks의 0부터 시작하는 위치
    evidence_ids: list[str] = Field(min_length=1)


class ActionCitation(BaseModel):
    action_index: int = Field(ge=0)
    evidence_ids: list[str] = Field(min_length=1)


class Evidence(BaseModel):
    """검색으로 찾은 문서 조각 하나. rag 모듈이 만들고 agent가 인용한다."""

    evidence_id: str  # 청크 고유 ID. AnalysisResult가 이 값으로 인용한다
    doc_id: str  # 예: BTT-MANUAL
    doc_version: str  # 예: 2.0
    title: str | None = None
    page: int | None = Field(
        default=None, ge=1, strict=True
    )  # 표지 포함 PDF 실제 페이지, 1부터
    section: str | None = None  # 예: "03 이송·광전 현장 대응 절차"
    text: str
    score: float | None = None
    citation: str  # 사람이 읽는 인용 문자열. 예: "BTT-MANUAL 2.0 3절 P01/P06"
    # 리랭커 모델 출력. 미사용 시 None(0과 다름). 확률이 아니며 모델별 보정 필요.
    relevance: float | None = Field(default=None, allow_inf_nan=False)
    report_timing: list[ReportActionTiming] = Field(default_factory=list)


class CauseCandidate(BaseModel):
    cause: str
    # 과거 결과만 보존하며 우선순위로 변환하지 않는다.
    likelihood: Likelihood | None = None
    inspection_priority: InspectionPriority | None = None
    priority_reason: str | None = None
    basis: str  # 후보와 문서 근거의 연결 설명(과거 결과에는 센서 요약)
    evidence_ids: list[str] = Field(default_factory=list)
    observations: list[str] = Field(
        default_factory=list
    )  # 서버가 검증한 관련 센서 관측
    unconfirmed: list[str] = Field(default_factory=list)  # 평가에 더 필요한 확인 항목

    @model_validator(mode="after")
    def priority_has_reason(self) -> Self:
        if self.inspection_priority is None:
            if self.likelihood is None:
                raise ValueError("점검 우선순위 또는 과거 가능성 등급이 필요합니다")
            if self.priority_reason is not None:
                raise ValueError("우선순위 없이 점검 순서의 근거를 저장할 수 없습니다")
        elif not self.priority_reason or not self.priority_reason.strip():
            raise ValueError("점검 우선순위에는 근거 설명이 필요합니다")
        return self


class MaintenanceReference(BaseModel):
    """과거 보고서 한 건의 참고 요약. 현재 사건의 실행 지시와 구분한다."""

    symptom: str = Field(min_length=1, max_length=400)
    action: str = Field(min_length=1, max_length=400)
    outcome: str = Field(min_length=1, max_length=400)
    similarity: str = Field(min_length=1, max_length=400)
    differences: str = Field(min_length=1, max_length=400)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


def validate_reference_sources(cases, evidence):
    """사례별 한 보고서·판본을 가리키고 같은 보고서를 중복 표시하지 않는다."""
    known = {item.evidence_id: item for item in evidence}
    seen = set()
    for case in cases:
        if not set(case.evidence_ids) <= known.keys():
            raise ValueError("참고 사례가 확보하지 않은 근거를 인용했습니다")
        sources = {
            (known[key].doc_id, known[key].doc_version) for key in case.evidence_ids
        }
        if len(sources) != 1:
            raise ValueError("참고 사례 하나에는 한 보고서의 같은 판본만 연결합니다")
        report_id, _ = next(iter(sources))
        if report_id in seen:
            raise ValueError("참고 사례에 같은 보고서를 중복 표시할 수 없습니다")
        seen.add(report_id)


class AnalysisResult(BaseModel):
    incident_id: str
    status: Literal["OK", "INSUFFICIENT_EVIDENCE", "VERIFICATION_FAILED", "FAILED"]
    observed_facts: str
    suspected_causes: list[CauseCandidate] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)  # 점검 순서
    check_citations: list[CheckCitation] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    action_citations: list[ActionCitation] = Field(default_factory=list)
    actions_requiring_approval: list[str] = Field(default_factory=list)
    approval_citations: list[ActionCitation] = Field(default_factory=list)
    additional_checks: list[str] = Field(default_factory=list)  # 근거 부족 시 확인할 것
    reference_cases: list[MaintenanceReference] = Field(
        default_factory=list, max_length=2
    )
    evidence: list[Evidence] = Field(default_factory=list)
    limitations: str | None = None
    model: str  # 예: "anthropic/claude-opus-5-5" (공급자/모델 ID)
    prompt_version: str | None = None
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def _citations_exist(self) -> Self:
        """근거가 없으면 멈춘다: OK 결과는 근거가 있어야 하고, 원인 후보마다 근거를 인용해야 하며,
        인용은 실제로 검색한 근거를 가리켜야 한다."""
        known = {e.evidence_id for e in self.evidence}
        validate_reference_sources(self.reference_cases, self.evidence)
        if self.status == "OK" and not known:
            raise ValueError("status=OK 인데 검색 근거가 없음")
        for cause in self.suspected_causes:
            if self.status == "OK" and not cause.evidence_ids:
                raise ValueError(f"근거를 인용하지 않은 원인 후보: {cause.cause}")
            missing = set(cause.evidence_ids) - known
            if missing:
                raise ValueError(f"없는 근거를 인용함: {sorted(missing)}")
        indices = [item.check_index for item in self.check_citations]
        if len(indices) != len(set(indices)):
            raise ValueError("점검 절차 인용 위치 중복")
        for item in self.check_citations:
            if item.check_index >= len(self.recommended_checks):
                raise ValueError("존재하지 않는 점검 절차를 인용함")
            if set(item.evidence_ids) - known:
                raise ValueError("점검 절차가 없는 근거를 인용함")
        for items, actions in (
            (self.action_citations, self.recommended_actions),
            (self.approval_citations, self.actions_requiring_approval),
        ):
            indices = [item.action_index for item in items]
            if len(indices) != len(set(indices)):
                raise ValueError("조치 인용 위치 중복")
            for item in items:
                if item.action_index >= len(actions) or set(item.evidence_ids) - known:
                    raise ValueError("조치 위치 또는 인용 근거가 유효하지 않음")
        return self
