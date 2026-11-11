"""검증 후 공개하는 채팅 SSE 계약. 초안·도구 인자·공급자 원문은 전송하지 않는다."""

from collections.abc import Callable
from typing import Literal
from uuid import UUID

from pydantic import Field

from weeing_weeing.contracts.chat import ChatModel, NonEmpty
from weeing_weeing.contracts.chat_storage import ChatRequestView

ChatPhase = Literal[
    "accepted", "generating", "searching", "verifying", "saving", "cache_hit"
]
ChatProgress = Callable[[ChatPhase], None]


class ChatStreamProgress(ChatModel):
    event: Literal["progress"] = "progress"
    request_id: UUID
    phase: ChatPhase


class ChatStreamDelta(ChatModel):
    event: Literal["delta"] = "delta"
    request_id: UUID
    # 경계의 공백·줄바꿈도 마크다운 본문이다. strip 하지 않는다.
    text: str = Field(min_length=1, max_length=2048)

    model_config = {"extra": "forbid", "str_strip_whitespace": False}


class ChatStreamDone(ChatModel):
    event: Literal["done"] = "done"
    request: ChatRequestView


class ChatStreamError(ChatModel):
    event: Literal["error"] = "error"
    status_code: Literal[404, 409, 500, 503]
    message: NonEmpty
    request_reserved: bool = True  # False인 경우에만 예약 전 거절로 판단한다.
