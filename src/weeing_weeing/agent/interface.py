from typing import TYPE_CHECKING, Any, Protocol

from weeing_weeing.agent.errors import (
    LlmError,
    LlmModelMissingError,
    LlmRefusedError,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
)
from weeing_weeing.contracts import AnalysisResult, Incident

if TYPE_CHECKING:
    from weeing_weeing.config import Settings
    from weeing_weeing.rag.interface import Retriever

__all__ = [
    "Analyzer",
    "LlmClient",
    "LlmError",
    "LlmModelMissingError",
    "LlmRefusedError",
    "LlmTimeoutError",
    "LlmUnavailableError",
    "LlmUsage",
    "get_analyzer",
    "get_llm_client",
]


class LlmClient(Protocol):
    """상용 LLM API 경계(현재 Claude). 에이전트(#11)와 챗봇(#89)이 같이 쓴다."""

    provider: str  # 예: anthropic. AnalysisResult.model은 "<provider>/<model_name>"
    model_name: str
    last_usage: LlmUsage | None  # 마지막 호출의 토큰·시간

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        """JSON 문자열을 돌려준다. schema(JSON 스키마)를 주면 그 모양으로만 생성한다.

        실패는 LlmError로 알린다(LlmTimeoutError·LlmUnavailableError·LlmModelMissingError·
        LlmRefusedError). 범위·길이 제약은 API가 강제하지 않으므로 호출한 쪽이 pydantic으로
        다시 검증한다.
        """
        ...

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_s: float,
    ) -> Any:
        """도구 호출 루프의 한 걸음. 응답(content의 tool_use·text 블록)을 그대로 돌려준다."""
        ...


class Analyzer(Protocol):
    def analyze(self, incident: Incident) -> AnalysisResult:
        """실패해도 예외 대신 status=FAILED 결과를 돌려준다(HMI에 '관리자 호출' 표시)."""
        ...


def get_llm_client(settings: "Settings | None" = None) -> LlmClient:
    """.env 설정(LLM_MODEL·LLM_EFFORT)으로 만든 Claude 클라이언트.

    API 키는 여기서 읽지 않는다. 첫 호출 때 SDK가 ANTHROPIC_API_KEY에서 읽는다.
    """
    from weeing_weeing.agent.claude import ClaudeClient
    from weeing_weeing.config import get_settings

    settings = settings or get_settings()
    return ClaudeClient(settings.llm_model, effort=settings.llm_effort)


def get_analyzer(
    retriever: "Retriever",
    *,
    client: LlmClient | None = None,
    settings: "Settings | None" = None,
) -> Analyzer:
    """사건 분석 에이전트(#102). 검색기는 조립하는 쪽(api·스크립트)이 넘긴다."""
    from weeing_weeing.agent.analyst import IncidentAnalyzer
    from weeing_weeing.config import get_settings

    settings = settings or get_settings()
    return IncidentAnalyzer(
        client or get_llm_client(settings),
        retriever,
        timeout_s=settings.llm_timeout_s,
        max_turns=settings.agent_max_turns,
    )
