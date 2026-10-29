"""FAQ 주제 탐색·질문 선택 계약. 선택한 ID와 버전으로만 검토 답변을 반환한다."""

from datetime import date
from typing import Annotated, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from weeing_weeing.contracts.chat import ChatFaqSource, ChatModel, NonEmpty

FaqId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"),
]
FaqVersion = Annotated[NonEmpty, Field(max_length=64)]


class FaqTopic(ChatModel):
    """화면에 표시할 주제. 목록 순서는 order, topic_id 순이다."""

    model_config = ConfigDict(frozen=True)

    topic_id: FaqId
    title: Annotated[NonEmpty, Field(max_length=100)]
    order: int = Field(default=0, ge=0, strict=True)


class FaqQuestion(ChatModel):
    """주제별 질문 목록 항목. 클릭 시 faq_id와 faq_version을 전송한다."""

    model_config = ConfigDict(frozen=True)

    faq_id: FaqId
    faq_version: FaqVersion
    topic_id: FaqId
    question: str = Field(min_length=1, max_length=2000)
    order: int = Field(default=0, ge=0, strict=True)


class FaqSelection(ChatModel):
    """선택 요청. 사용자 ID·답변 본문을 클라이언트로부터 받지 않는다."""

    request_id: UUID
    faq_id: FaqId
    faq_version: FaqVersion


class FaqAnswer(ChatModel):
    """서버의 검토된 질문·답변. 저장 계층은 이 스냅샷과 출처 버전을 보존한다."""

    model_config = ConfigDict(frozen=True)

    question: FaqQuestion
    answer: Annotated[NonEmpty, Field(max_length=4000)]
    reviewed_at: date
    source: ChatFaqSource

    @model_validator(mode="after")
    def _source_matches(self) -> Self:
        if (
            self.question.faq_id != self.source.faq_id
            or self.question.faq_version != self.source.faq_version
        ):
            raise ValueError("FAQ 질문과 출처의 ID·버전이 다름")
        return self
