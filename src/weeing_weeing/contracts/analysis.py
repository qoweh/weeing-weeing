"""RAG 검색 근거(Evidence)와 AI 분석 결과(AnalysisResult) 계약.

출처: 1차 분담 'AI Agent 개발 4. 결과 구조화 및 검증', 노션 '김민우 (정리본)' 보고서 예시의
ai_analysis 칸. AI는 제안까지만 하고 원인 확정·재가동은 사람이 한다.
"""

from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator

Likelihood = Literal["상", "중", "하"]


class Evidence(BaseModel):
    """검색으로 찾은 문서 조각 하나. rag 모듈이 만들고 agent가 인용한다."""

    evidence_id: str  # 청크 고유 ID. AnalysisResult가 이 값으로 인용한다
    doc_id: str  # 예: BTT-MANUAL
    doc_version: str  # 예: 2.0
    section: str | None = None  # 예: "03 이송·광전 현장 대응 절차"
    text: str
    score: float | None = None
    citation: str  # 사람이 읽는 인용 문자열. 예: "BTT-MANUAL 2.0 3절 P01/P06"
    # 리랭커 모델 출력. 미사용 시 None(0과 다름). 확률이 아니며 모델별 보정 필요.
    relevance: float | None = Field(default=None, allow_inf_nan=False)


class CauseCandidate(BaseModel):
    cause: str
    likelihood: Likelihood
    basis: str  # 센서 근거 요약
    evidence_ids: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    incident_id: str
    status: Literal["OK", "INSUFFICIENT_EVIDENCE", "FAILED"]
    observed_facts: str
    suspected_causes: list[CauseCandidate] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)  # 점검 순서
    recommended_actions: list[str] = Field(default_factory=list)
    actions_requiring_approval: list[str] = Field(default_factory=list)
    additional_checks: list[str] = Field(default_factory=list)  # 근거 부족 시 확인할 것
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
        if self.status == "OK" and not known:
            raise ValueError("status=OK 인데 검색 근거가 없음")
        for cause in self.suspected_causes:
            if self.status == "OK" and not cause.evidence_ids:
                raise ValueError(f"근거를 인용하지 않은 원인 후보: {cause.cause}")
            missing = set(cause.evidence_ids) - known
            if missing:
                raise ValueError(f"없는 근거를 인용함: {sorted(missing)}")
        return self
