"""#90: 개인 대화 저장·중복 요청 계약. 사용자 ID는 본문으로 받지 않는다."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from weeing_weeing.contracts.chat import (
    ChatConversation,
    ChatModel,
    ChatResponse,
    ChatSearchConditions,
    NonEmpty,
)
from weeing_weeing.contracts.faq import FaqId

ChatRequestState = Literal["RESERVED", "RUNNING", "COMPLETED", "FAILED", "UNKNOWN"]


class ChatSubmission(ChatModel):
    """같은 ID의 동일 본문만 재전송할 수 있다. conditions 생략은 대화 선택 조건 사용이다."""

    request_id: UUID
    kind: Literal["CHAT", "FAQ"]
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    faq_id: FaqId | None = None
    conditions: ChatSearchConditions | None = None
    model: str | None = None

    @model_validator(mode="after")
    def _kind(self) -> Self:
        if self.kind == "CHAT":
            if self.question is None or self.faq_id is not None:
                raise ValueError("자유 질문에는 질문 본문만 필요함")
        elif self.question is not None or self.faq_id is None or self.model is not None:
            raise ValueError("FAQ 선택에는 FAQ ID만 필요함")
        return self


class ChatRequestView(ChatModel):
    conversation_id: UUID
    submission: ChatSubmission
    state: ChatRequestState
    conditions: ChatSearchConditions
    response: ChatResponse | None = None
    cache_hit: bool = False
    retry_allowed: bool = False
    error_code: (
        Literal[
            "PREPARATION_FAILED",
            "FAQ_NOT_FOUND",
            "EXPIRED_BEFORE_START",
            "RESULT_UNKNOWN",
        ]
        | None
    ) = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _state(self) -> Self:
        if (self.state == "COMPLETED") != (self.response is not None):
            raise ValueError("완료 요청에만 저장된 응답이 필요함")
        if self.response and self.response.request_id != self.submission.request_id:
            raise ValueError("질문과 답변의 요청 ID가 다름")
        if self.retry_allowed and self.state != "FAILED":
            raise ValueError("실행 전 실패만 같은 ID로 명시적 재시도 가능")
        return self


class ChatSavedMessage(ChatModel):
    sequence: int = Field(ge=1, strict=True)
    request_id: UUID
    kind: Literal["CHAT", "FAQ"]
    role: Literal["user", "assistant"]
    content: NonEmpty
    state: ChatRequestState
    response: ChatResponse | None = None
    created_at: AwareDatetime


class ChatConversationPage(ChatModel):
    conversation: ChatConversation
    messages: list[ChatSavedMessage] = Field(default_factory=list, max_length=200)
    has_more: bool
