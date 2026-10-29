"""챗봇 경계 계약(#86). 권한 검사·검색·생성·저장은 후속 단계에서 구현한다."""

from datetime import date
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ChatIntent = Literal["MANUAL", "MAINTENANCE_HISTORY", "FAQ", "COMBINED", "OUT_OF_SCOPE"]
ChatStatus = Literal[
    "OK", "NEEDS_CLARIFICATION", "INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE", "FAILED"
]


class ChatModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChatSearchConditions(ChatModel):
    """요청 검색 조건. 권한을 부여하는 조건이 아니며 서버가 허용 범위와 교차한다.

    기간은 보고서의 실제 조치일 기준, 양 끝 날짜 포함. 정확한 집계는 DB로 처리한다.
    """

    asset_id: Annotated[NonEmpty, Field(max_length=100)] | None = None
    model: Annotated[NonEmpty, Field(max_length=100)] | None = None
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=5, ge=1, le=20, strict=True)

    @model_validator(mode="after")
    def _period(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("검색 시작일은 종료일보다 늦을 수 없음")
        return self


class ChatQuestion(ChatModel):
    """사용자 요청. 사용자 ID·의도·권한·이전 대화는 클라이언트가 지정하지 않는다."""

    request_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    conditions: ChatSearchConditions = Field(default_factory=ChatSearchConditions)


class ChatDocumentSource(ChatModel):
    kind: Literal["DOCUMENT"] = "DOCUMENT"
    source_id: NonEmpty
    title: NonEmpty
    doc_id: NonEmpty
    doc_version: NonEmpty
    page: int | None = Field(default=None, ge=1, strict=True)
    section: NonEmpty | None = None

    @model_validator(mode="after")
    def _location(self) -> Self:
        if self.page is None and self.section is None:
            raise ValueError("문서 출처에는 페이지 또는 절이 필요함")
        return self


class ChatReportSource(ChatModel):
    kind: Literal["REPORT"] = "REPORT"
    source_id: NonEmpty
    title: NonEmpty
    report_id: NonEmpty
    report_version: int = Field(ge=1, strict=True)
    # 생략 금지: 가상 사례를 실제 사례로 오인하지 않게 한다.
    synthetic: bool = Field(strict=True)


class ChatFaqSource(ChatModel):
    kind: Literal["FAQ"] = "FAQ"
    source_id: NonEmpty
    title: NonEmpty
    faq_id: NonEmpty
    faq_version: NonEmpty


ChatSource = Annotated[
    ChatDocumentSource | ChatReportSource | ChatFaqSource, Field(discriminator="kind")
]


class ChatFailure(ChatModel):
    code: Literal[
        "ACCESS_DENIED",  # 해당 대화·문서·보고서를 열람할 권한 없음
        "TIMEOUT",  # 검색·응답 생성 등이 제한 시간 안에 완료되지 않음
        "LLM_AUTHENTICATION",  # LLM 공급자 인증 실패(API 키·권한 문제)
        "RATE_LIMITED",  # 서비스 또는 LLM 공급자의 호출 제한 초과
        "LLM_SERVICE",  # LLM 공급자 서비스 장애(예: 5xx)
        "INVALID_RESPONSE",  # 생성 응답의 형식·인용 검증 실패
        "SEARCH_UNAVAILABLE",  # 검색 저장소·임베딩·리랭커 등 검색 기능 장애
        "STORAGE_UNAVAILABLE",  # DB 연결 실패 등 대화 조회·저장 기능 장애
        "INTERNAL_ERROR",  # 위 항목으로 분류되지 않는 내부 처리 오류
    ]
    retryable: bool = Field(strict=True)  # 같은 요청을 재시도할 수 있는지 여부


class ChatAnswerPart(ChatModel):
    """매뉴얼 기준·과거 사례·FAQ를 구분하는 답변 단위."""

    kind: Literal["MANUAL", "MAINTENANCE_HISTORY", "FAQ"]
    text: NonEmpty
    source_ids: list[NonEmpty] = Field(min_length=1, max_length=20)


class ChatResponse(ChatModel):
    request_id: UUID
    intent: ChatIntent
    status: ChatStatus
    applied_conditions: ChatSearchConditions
    message: NonEmpty  # 사용자 안내. OK의 근거 기반 본문은 parts에 둔다
    parts: list[ChatAnswerPart] = Field(default_factory=list, max_length=20)
    sources: list[ChatSource] = Field(default_factory=list, max_length=20)
    clarification_questions: list[NonEmpty] = Field(default_factory=list, max_length=5)
    failure: ChatFailure | None = None
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def _state_and_citations(self) -> Self:
        known = {s.source_id: s.kind for s in self.sources}
        if len(known) != len(self.sources):
            raise ValueError("출처 ID가 중복됨")
        if self.status == "OK":
            if not self.parts or not self.sources:
                raise ValueError("정상 답변에는 본문과 근거가 필요함")
        elif self.parts or self.sources:
            raise ValueError("정상 답변 외 상태에는 답변 본문·출처를 싣지 않음")
        if (self.status == "FAILED") != (self.failure is not None):
            raise ValueError("처리 실패에만 오류 종류가 필요함")
        if (self.status == "NEEDS_CLARIFICATION") != bool(self.clarification_questions):
            raise ValueError("추가 질문 상태에만 확인 질문이 필요함")
        if self.status == "OUT_OF_SCOPE" and self.intent != "OUT_OF_SCOPE":
            raise ValueError("범위 밖 응답은 범위 밖 의도여야 함")
        if self.intent == "OUT_OF_SCOPE" and self.status not in {
            "OUT_OF_SCOPE",
            "FAILED",
        }:
            raise ValueError("범위 밖 의도에는 정상 답변을 생성하지 않음")
        expected = {"MANUAL": "DOCUMENT", "MAINTENANCE_HISTORY": "REPORT", "FAQ": "FAQ"}
        for part in self.parts:
            if self.intent != "COMBINED" and part.kind != self.intent:
                raise ValueError("답변 종류가 질문 의도와 다름")
            if any(known.get(key) != expected[part.kind] for key in part.source_ids):
                raise ValueError("인용 출처가 없거나 답변 종류와 다름")
        return self


class ChatTurn(ChatModel):
    """서버가 소유권 검사 후 준비하는 최근 대화. 시스템/도구 메시지는 허용하지 않는다."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatConversation(ChatModel):
    conversation_id: UUID
    title: Annotated[NonEmpty, Field(max_length=100)]
    conditions: ChatSearchConditions
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _timestamps(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("대화 갱신 시각은 생성 시각보다 빠를 수 없음")
        return self


class ChatContext(ChatModel):
    """서버가 조회·권한 검사·길이 제한을 마친 문맥. LLM 전달량에 상한을 둔다."""

    recent_turns: list[ChatTurn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _size(self) -> Self:
        if sum(len(turn.content) for turn in self.recent_turns) > 16000:
            raise ValueError("최근 대화는 합계 16000자 이내여야 함")
        return self
