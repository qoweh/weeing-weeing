"""파일 기반 FAQ 조회. 네트워크·LLM·임베딩·DB 없이 선택한 검토 답변만 반환한다."""

import tomllib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator

from weeing_weeing.contracts.chat import (
    ChatAnswerPart,
    ChatFaqSource,
    ChatModel,
    ChatResponse,
    ChatSearchConditions,
    NonEmpty,
)
from weeing_weeing.contracts.faq import (
    FaqAnswer,
    FaqId,
    FaqQuestion,
    FaqSelection,
    FaqTopic,
    FaqVersion,
)

DEFAULT_FAQ_PATH = Path(__file__).resolve().parents[3] / "data/faq/service_v1.toml"


class FaqCatalogError(RuntimeError):
    """파일 읽기·구조 검증 실패. 빈 FAQ나 LLM 답변으로 자동 우회하지 않는다."""


class FaqNotFoundError(LookupError):
    """없는 항목과 비활성·미검토 항목을 같은 오류로 취급한다."""


class FaqVersionConflictError(ValueError):
    """화면의 FAQ 버전과 현재 답변 버전이 다르다. 목록을 다시 조회해야 한다."""


class _TopicRecord(FaqTopic):
    active: bool = Field(default=False, strict=True)


class _FaqRecord(ChatModel):
    faq_id: FaqId
    faq_version: FaqVersion
    topic_id: FaqId
    question: str = Field(min_length=1, max_length=2000)
    order: int = Field(default=0, ge=0, strict=True)
    active: bool = Field(default=False, strict=True)
    aliases: tuple[NonEmpty, ...] = ()  # 참고 표현이며 자동 매칭에는 사용하지 않는다
    answer: str = Field(default="", max_length=4000)
    reviewed_at: date | None = None
    references: tuple[NonEmpty, ...] = ()  # 작성 시 확인한 코드·문서 위치

    @model_validator(mode="after")
    def _reviewed(self) -> Self:
        if self.active and (
            not self.answer or self.reviewed_at is None or not self.references
        ):
            raise ValueError("활성 FAQ에는 답변·검토일·근거가 필요함")
        if self.reviewed_at is not None and self.reviewed_at > date.today():
            raise ValueError("FAQ 검토일은 미래일 수 없음")
        return self


class _CatalogData(ChatModel):
    schema_version: Literal[1]
    topics: tuple[_TopicRecord, ...] = ()
    faqs: tuple[_FaqRecord, ...] = ()

    @model_validator(mode="after")
    def _unique_ids_and_topics(self) -> Self:
        topics = {topic.topic_id for topic in self.topics}
        ids = {faq.faq_id for faq in self.faqs}
        if len(topics) != len(self.topics) or len(ids) != len(self.faqs):
            raise ValueError("FAQ·주제 ID가 중복됨")
        if any(faq.topic_id not in topics for faq in self.faqs):
            raise ValueError("존재하지 않는 주제의 FAQ가 있음")
        return self


class FileFaqCatalog:
    """검증된 파일 한 판의 메모리 스냅샷. 변경 후 다시 load해야 반영된다."""

    def __init__(self, path: Path) -> None:
        try:
            data = _CatalogData.model_validate(tomllib.loads(path.read_text("utf-8")))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValidationError) as exc:
            raise FaqCatalogError("FAQ 파일을 읽거나 검증하지 못했습니다.") from exc
        topics = {topic.topic_id: topic for topic in data.topics if topic.active}
        self._answers: dict[str, FaqAnswer] = {}
        self._questions: dict[str, list[FaqQuestion]] = {}
        for record in data.faqs:
            if not record.active or record.topic_id not in topics:
                continue
            question = FaqQuestion(
                **record.model_dump(
                    include={"faq_id", "faq_version", "topic_id", "question", "order"}
                )
            )
            self._questions.setdefault(record.topic_id, []).append(question)
            self._answers[record.faq_id] = FaqAnswer(
                question=question,
                answer=record.answer,
                reviewed_at=record.reviewed_at,
                source=ChatFaqSource(
                    source_id=f"faq:{record.faq_id}:{record.faq_version}",
                    title=record.question,
                    faq_id=record.faq_id,
                    faq_version=record.faq_version,
                ),
            )
        self._topics = tuple(
            sorted(
                (
                    FaqTopic(**topic.model_dump(exclude={"active"}))
                    for key, topic in topics.items()
                    if key in self._questions
                ),
                key=lambda topic: (topic.order, topic.topic_id),
            )
        )
        for questions in self._questions.values():
            questions.sort(key=lambda question: (question.order, question.faq_id))

    def list_topics(self) -> list[FaqTopic]:
        """활성·검토 완료 질문이 하나 이상인 활성 주제만 반환한다."""
        return list(self._topics)

    def list_questions(self, topic_id: str) -> list[FaqQuestion]:
        """목록에 없는 주제는 빈 목록 대신 동일한 조회 불가 오류를 반환한다."""
        if topic_id not in self._questions:
            raise FaqNotFoundError("조회할 수 없는 FAQ 주제입니다.")
        return list(self._questions[topic_id])

    def get_answer(self, faq_id: str) -> FaqAnswer:
        try:
            # source는 기존 가변 ChatFaqSource 모델이므로 깊은 복사로 내부 상태를 보호한다.
            return self._answers[faq_id].model_copy(deep=True)
        except KeyError as exc:
            raise FaqNotFoundError("조회할 수 없는 FAQ입니다.") from exc

    def answer(
        self,
        selection: FaqSelection,
        *,
        conditions: ChatSearchConditions | None = None,
    ) -> ChatResponse:
        """ID 선택을 기존 챗봇 응답으로 변환한다. 조건은 보존하며 검색하지 않는다."""
        faq = self.get_answer(selection.faq_id)
        if selection.faq_version != faq.source.faq_version:
            raise FaqVersionConflictError(
                "FAQ가 변경됐습니다. 질문 목록을 새로고침하세요."
            )
        return ChatResponse(
            request_id=selection.request_id,
            intent="FAQ",
            status="OK",
            applied_conditions=conditions or ChatSearchConditions(),
            message="검토된 FAQ 답변입니다.",
            parts=[
                ChatAnswerPart(
                    kind="FAQ", text=faq.answer, source_ids=[faq.source.source_id]
                )
            ],
            sources=[faq.source],
            generated_at=datetime.now(timezone.utc),
        )
