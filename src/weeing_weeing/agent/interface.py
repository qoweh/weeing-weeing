from typing import TYPE_CHECKING, Any, Protocol

from weeing_weeing.agent.errors import (
    LlmError,
    LlmModelMissingError,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
)
from weeing_weeing.contracts import AnalysisResult, Incident

if TYPE_CHECKING:
    from weeing_weeing.config import Settings

__all__ = [
    "Analyzer",
    "LlmClient",
    "LlmError",
    "LlmModelMissingError",
    "LlmTimeoutError",
    "LlmUnavailableError",
    "LlmUsage",
    "get_llm_client",
]


class LlmClient(Protocol):
    """Ollama와 상용 API를 바꿔 끼울 수 있게 하는 경계(품질·토큰 비교 평가용)."""

    model_name: str

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        """JSON 문자열을 돌려준다. schema(JSON 스키마)를 주면 그 모양으로만 생성한다.

        실패는 LlmError로 알린다(LlmTimeoutError·LlmUnavailableError·LlmModelMissingError).
        돌려준 문자열이 스키마를 지키는지는 호출한 쪽이 pydantic으로 다시 검증한다.
        """
        ...


class Analyzer(Protocol):
    def analyze(self, incident: Incident) -> AnalysisResult:
        """실패해도 예외 대신 status=FAILED 결과를 돌려준다(HMI에 '관리자 호출' 표시)."""
        ...


def get_llm_client(settings: "Settings | None" = None) -> LlmClient:
    """.env 설정(OLLAMA_*)으로 만든 클라이언트. OLLAMA_MODEL이 비어 있으면 ValueError."""
    from weeing_weeing.agent.ollama import OllamaClient
    from weeing_weeing.config import get_settings

    settings = settings or get_settings()
    return OllamaClient(
        settings.ollama_base_url,
        settings.ollama_model,
        think=settings.ollama_think,
        keep_alive=settings.ollama_keep_alive,
    )
