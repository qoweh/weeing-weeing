"""LLM 호출 결과 타입. 공급자(현재 Claude)와 무관하게 쓴다."""

from dataclasses import dataclass


class LlmError(RuntimeError):
    """LLM 호출 실패. 메시지는 로그·화면에 그대로 보여도 되는 내용만 담는다."""


class LlmUnavailableError(LlmError):
    """서버에 연결하지 못했거나 인증 정보(API 키)가 없다·틀렸다."""


class LlmModelMissingError(LlmError):
    """그 모델 ID를 쓸 수 없다(오타·권한 없음)."""


class LlmTimeoutError(LlmError):
    """제한 시간 안에 응답이 오지 않았다."""


class LlmRefusedError(LlmError):
    """모델이 안전 정책으로 답하지 않았다(대체 모델까지 거부)."""


@dataclass(frozen=True)
class LlmUsage:
    """호출 한 번(또는 여러 번 합친)의 토큰 수와 시간. 비용·속도 비교용."""

    input_tokens: int
    output_tokens: int
    total_s: float  # 요청을 보내고 응답을 다 받기까지

    @property
    def tokens_per_s(self) -> float:
        """출력 속도(대략). 네트워크·대기 시간이 포함된 값이다."""
        return self.output_tokens / self.total_s if self.total_s else 0.0

    def __add__(self, other: "LlmUsage") -> "LlmUsage":
        return LlmUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.total_s + other.total_s,
        )
