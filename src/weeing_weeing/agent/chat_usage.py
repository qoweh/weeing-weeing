"""챗봇 요청 하나의 호출별 사용량. 키·질문·응답 본문은 저장하지 않는다."""

from dataclasses import dataclass

from weeing_weeing.agent.errors import LlmUsage


@dataclass(frozen=True)
class ChatCallUsage:
    purpose: str
    provider: str
    model: str
    usage: LlmUsage | None
    elapsed_s: float
    failed: bool
    attempts: int = 1


@dataclass(frozen=True)
class ChatRunUsage:
    request_id: str = ""
    calls: tuple[ChatCallUsage, ...] = ()
    tool_names: tuple[str, ...] = ()
    elapsed_s: float = 0

    @property
    def unknown_calls(self) -> int:
        return sum(call.usage is None or call.attempts > 1 for call in self.calls)

    @property
    def total(self) -> LlmUsage | None:
        # 누락된 사용량을 0으로 채워 비용을 과소 집계하지 않도록 합계도 미확인으로 둔다.
        if self.unknown_calls:
            return None
        total = LlmUsage(0, 0, 0)
        for call in self.calls:
            total += call.usage
        return total
