"""LLM 호출 결과 타입. 공급자(현재 Claude)와 무관하게 쓴다."""

from dataclasses import dataclass


class LlmError(RuntimeError):
    """LLM 호출 실패. 메시지는 로그·화면에 그대로 보여도 되는 내용만 담는다."""


class LlmUnavailableError(LlmError):
    """서버에 연결하지 못했거나 인증 정보(API 키)가 없다·틀렸다."""


class LlmRequestError(LlmError):
    """공급자 HTTP 오류. 같은 설정의 평가 요청을 반복하지 않는다."""

    def __init__(self, status_code: int, *, parameter_hint: str | None = None):
        self.status_code = status_code
        self.parameter_hint = parameter_hint
        super().__init__(
            f"Claude API 오류 HTTP {status_code}"
            + (f" ({parameter_hint})" if parameter_hint else "")
        )


class LlmAuthenticationError(LlmUnavailableError):
    """API 키·프로필·공급자 권한 오류. 자동 재시도하지 않는다."""


class LlmRateLimitError(LlmRequestError):
    """공급자의 429 호출 제한. 제한된 재시도 후에도 해소되지 않았다."""


class LlmServiceError(LlmUnavailableError):
    """네트워크·5xx 일시 장애. 인증 오류와 구분한다."""


class LlmInvalidResponseError(LlmError):
    """빈 응답·출력 잘림 등 정상 답변으로 처리할 수 없는 공급자 응답."""


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
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def tokens_per_s(self) -> float:
        """출력 속도(대략). 네트워크·대기 시간이 포함된 값이다."""
        return self.output_tokens / self.total_s if self.total_s else 0.0

    def __add__(self, other: "LlmUsage") -> "LlmUsage":
        return LlmUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.total_s + other.total_s,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
        )
