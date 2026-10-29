"""자유 대화 공통 검색 도구 입력·출력. 직책별 열람 ACL 없이 조건·출처 상태를 검증한다."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from weeing_weeing.contracts.chat import (
    ChatDocumentSource,
    ChatModel,
    ChatReportSource,
    ChatSearchConditions,
    NonEmpty,
)
from weeing_weeing.contracts.codes import CODES


class ChatSearchQuery(ChatModel):
    query: str = Field(min_length=1, max_length=2000)
    kind: Literal["MANUAL", "MAINTENANCE_HISTORY"]
    conditions: ChatSearchConditions = Field(default_factory=ChatSearchConditions)
    code: NonEmpty | None = None

    @model_validator(mode="after")
    def _known_code(self) -> Self:
        if self.code is not None and self.code not in CODES:
            raise ValueError("정의되지 않은 설비 오류 코드")
        return self


class ChatSearchHit(ChatModel):
    """검색기가 필터·최신 승인/개정 상태를 검사해 만든 공통 근거 하나.

    실제 문서 위치·보고서 가상 여부는 서버 메타데이터에서 얻고 LLM이 만들지 않는다.
    검색 결과에 점수가 있다는 이유만으로 관련 근거라고 간주하지 않는다(#74·#75).
    """

    source: Annotated[
        ChatDocumentSource | ChatReportSource, Field(discriminator="kind")
    ]
    text: Annotated[NonEmpty, Field(max_length=8000)]
