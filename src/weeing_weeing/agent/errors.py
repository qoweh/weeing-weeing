"""LLM 호출 결과 타입. 공급자(Ollama·상용 API)와 무관하게 쓴다."""

from dataclasses import dataclass


class LlmError(RuntimeError):
    """LLM 호출 실패. 메시지는 로그·화면에 그대로 보여도 되는 내용만 담는다."""


class LlmUnavailableError(LlmError):
    """서버에 연결하지 못했다(꺼짐, 주소 오류 등)."""


class LlmModelMissingError(LlmError):
    """서버에 그 모델이 없다."""


class LlmTimeoutError(LlmError):
    """제한 시간 안에 응답이 오지 않았다."""


@dataclass(frozen=True)
class LlmUsage:
    """마지막 호출의 토큰 수와 시간. 모델 비교·튜닝용."""

    prompt_tokens: int
    output_tokens: int
    total_s: float  # 요청 전체(모델 로딩·프롬프트 처리·생성)
    load_s: float  # 모델 로딩
    eval_s: float  # 출력 생성만

    @property
    def tokens_per_s(self) -> float:
        """생성 속도. 프롬프트 길이·로딩과 무관하게 모델끼리 비교할 수 있다."""
        return self.output_tokens / self.eval_s if self.eval_s else 0.0
