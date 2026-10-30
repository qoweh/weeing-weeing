from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from weeing_weeing.agent.chat_usage import ChatCallUsage, ChatRunUsage
from weeing_weeing.agent.errors import (
    LlmAuthenticationError,
    LlmError,
    LlmInvalidResponseError,
    LlmModelMissingError,
    LlmRateLimitError,
    LlmRefusedError,
    LlmRequestError,
    LlmServiceError,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
)
from weeing_weeing.agent.faq import (
    FaqCatalogError,
    FaqNotFoundError,
    FaqVersionConflictError,
)
from weeing_weeing.agent.llm_check import (
    CheckReport,
    check_case,
)
from weeing_weeing.agent.llm_check import (
    format_markdown as format_llm_check,
)
from weeing_weeing.agent.llm_check import (
    load_cases as load_llm_cases,
)
from weeing_weeing.agent.llm_check import (
    report_data as llm_check_data,
)
from weeing_weeing.agent.llm_check import (
    run_check as run_llm_check,
)
from weeing_weeing.agent.runtime import ToolInputError as InvalidChatQueryError
from weeing_weeing.agent.sensor_window import SensorBatch, SensorReader
from weeing_weeing.agent.tracing import Tracer
from weeing_weeing.contracts import AnalysisResult, Incident
from weeing_weeing.contracts.chat import (
    ChatContext,
    ChatDocumentSource,
    ChatHistorySource,
    ChatQuestion,
    ChatReportSource,
    ChatResponse,
    ChatSearchConditions,
)
from weeing_weeing.contracts.chat_tools import (
    ChatHistoryQuery,
    ChatHistoryResult,
    ChatSearchHit,
    ChatSearchQuery,
)
from weeing_weeing.contracts.faq import FaqAnswer, FaqQuestion, FaqSelection, FaqTopic

if TYPE_CHECKING:
    from weeing_weeing.config import Settings
    from weeing_weeing.rag.interface import Retriever

__all__ = [
    "CheckReport",
    "check_case",
    "format_llm_check",
    "load_llm_cases",
    "llm_check_data",
    "run_llm_check",
    "Analyzer",
    "SensorBatch",
    "SensorReader",
    "ChatService",
    "ChatCallUsage",
    "ChatRunUsage",
    "ChatKnowledge",
    "InvalidChatQueryError",
    "get_chat_service",
    "FaqCatalog",
    "FaqCatalogError",
    "FaqNotFoundError",
    "FaqVersionConflictError",
    "load_faq_catalog",
    "LlmClient",
    "LlmError",
    "LlmAuthenticationError",
    "LlmRateLimitError",
    "LlmServiceError",
    "LlmInvalidResponseError",
    "LlmRequestError",
    "LlmModelMissingError",
    "LlmRefusedError",
    "LlmTimeoutError",
    "LlmUnavailableError",
    "LlmUsage",
    "Tracer",
    "get_analyzer",
    "get_llm_client",
]


class LlmClient(Protocol):
    """상용 LLM API 경계(현재 Claude). 에이전트(#11)와 챗봇(#89)이 같이 쓴다."""

    provider: str  # 예: anthropic. AnalysisResult.model은 "<provider>/<model_name>"
    model_name: str
    last_usage: LlmUsage | None  # 마지막 호출의 토큰·시간
    tracer: Tracer  # 사용량 기록(#113). 설정이 없으면 아무것도 안 하는 기록기

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


class ChatService(Protocol):
    last_run: (
        ChatRunUsage | None
    )  # 요청 ID를 대조해 읽는 최근 실행 통계. 본문·키는 포함하지 않는다.

    def reply(
        self,
        question: ChatQuestion,
        *,
        context: ChatContext,
        timeout_s: float,
    ) -> ChatResponse:
        """권한 검증된 문맥으로 응답한다. 장애는 FAILED, 근거 부족은 별도 상태다.

        API가 인증·대화 소유권을 검사하고 조건 검증 검색기·공용 LLM을 주입한다.
        저장소 조립·응답 저장도 API 책임이다. 동기 경계이므로 API는 작업 스레드에서
        실행하고 timeout_s 전체 예산을 검색·LLM에 나누어 적용한다(#91).
        """
        ...


class ChatKnowledge(Protocol):
    """직책에 따른 문서 ACL 없이 사용하는 공통 검색 경계(#88·#91).

    원시 Retriever를 직접 주입하지 않는다. 사용자 ID/권한은 도구 입력에 포함하지 않는다.
    구현체는 DB 공개 인터페이스로 검색 대상의 최신 판·승인 상태를 확인한다.
    사번·결재·AI 분석을 제거한 최소 본문만 반환하며 기간·설비 조건을 무시하지 않는다.
    """

    def validate_query(self, query: ChatSearchQuery, *, timeout_s: float) -> None:
        """설비·모델 실재 여부와 필터 지원·기간을 검증한다. 변경 없이 수락하거나 거부한다.

        미지원/모호한 조건은 InvalidChatQueryError(안전한 설명만)다.
        직책·작성자로 문서 검색을 제한하지 않는다. 정확한 집계는 DB 경로를 사용한다.
        """
        ...

    def search(
        self, query: ChatSearchQuery, *, timeout_s: float
    ) -> list[ChatSearchHit]:
        """조건·검색 대상 정책을 적용한 공통 근거와 서버 출처를 반환한다. 장애는 예외다."""
        ...

    def query_history(
        self, query: ChatHistoryQuery, *, timeout_s: float
    ) -> ChatHistoryResult:
        """DB의 전체 최신 승인 판으로 정확한 건수·제한된 목록·조회 출처를 반환한다."""
        ...

    def is_searchable(
        self,
        source: ChatDocumentSource | ChatReportSource | ChatHistorySource,
        *,
        timeout_s: float,
    ) -> bool:
        """삭제·개정·승인 상태를 재확인한다. 사용자별 열람 권한을 검사하지 않는다."""
        ...


def get_chat_service(
    knowledge: ChatKnowledge,
    *,
    faq: "FaqCatalog | None" = None,
    client: LlmClient | None = None,
    settings: "Settings | None" = None,
) -> ChatService:
    """기존 Claude를 쓰는 자유 대화. 조건·출처 상태 검증 검색기를 API가 주입한다."""
    from weeing_weeing.agent.chat import ToolChatService
    from weeing_weeing.config import get_settings

    settings = settings or get_settings()
    return ToolChatService(
        client
        if client is not None
        else get_llm_client(settings, entrypoint="chatbot"),
        knowledge,
        faq if faq is not None else load_faq_catalog(),
        max_turns=min(settings.agent_max_turns, 12),
    )


class FaqCatalog(Protocol):
    """일반 이용 안내 FAQ 조회 경계. 인증·대화 저장은 API에서 조립한다."""

    def list_topics(self) -> list[FaqTopic]:
        """활성·검토 완료 질문이 있는 주제만 정렬해 반환한다."""
        ...

    def list_questions(self, topic_id: str) -> list[FaqQuestion]:
        """공개 주제의 질문 목록. 조회 불가 주제는 FaqNotFoundError다."""
        ...

    def get_answer(self, faq_id: str) -> FaqAnswer:
        """서버에 있는 검토 답변 스냅샷. 조회 불가 FAQ는 FaqNotFoundError다."""
        ...

    def answer(
        self,
        selection: FaqSelection,
        *,
        conditions: ChatSearchConditions | None = None,
    ) -> ChatResponse:
        """선택 답변을 챗봇 응답으로 반환한다. 오래된 버전은 FaqVersionConflictError다.

        LLM·임베딩·검색·DB를 호출하지 않는다. 예외를 LLM 자동 호출로 처리하지 않는다.
        저장할 대표 질문·답변은 get_answer()에서 서버 데이터로 얻는다.
        """
        ...


def load_faq_catalog(path: Path | None = None) -> FaqCatalog:
    """TOML 파일을 검증해 새 스냅샷을 만든다. 실패는 FaqCatalogError다.

    경로 생략 시 저장소 data/faq/service_v1.toml을 읽는다. API는 앱 수명주기에
    로드한 인스턴스를 재사용하고 데이터 변경 시 새 인스턴스를 주입한다(#91).
    기존 인스턴스의 파일을 요청마다 다시 읽거나 자동 갱신하지 않는다.
    """
    from weeing_weeing.agent.faq import DEFAULT_FAQ_PATH, FileFaqCatalog

    return FileFaqCatalog(path if path is not None else DEFAULT_FAQ_PATH)


def get_llm_client(
    settings: "Settings | None" = None,
    *,
    entrypoint: str = "app",
    api_key: str | None = None,
) -> LlmClient:
    """.env 설정(LLM_MODEL·LLM_EFFORT)으로 만든 Claude 클라이언트.

    api_key를 전달하면 숨김 입력한 메모리의 키를 사용한다. 생략하면 첫 호출 때 SDK가
    환경변수/로그인 프로필을 읽는다. 키는 추적·로그에 전달하지 않는다.
    entrypoint는 사용량 기록의 기능 태그다(예: analyze, llm-check, api, chatbot).
    LANGFUSE_* 설정이 있으면 호출이 Langfuse에 남는다(docs/USAGE_TRACKING.md).
    """
    from weeing_weeing.agent.claude import ClaudeClient
    from weeing_weeing.agent.tracing import build_tracer
    from weeing_weeing.config import get_settings

    settings = settings or get_settings()
    return ClaudeClient(
        settings.llm_model,
        effort=settings.llm_effort,
        tracer=build_tracer(settings, entrypoint=entrypoint),
        api_key=api_key,
    )


def get_analyzer(
    retriever: "Retriever",
    *,
    client: LlmClient | None = None,
    settings: "Settings | None" = None,
    sensor_reader: SensorReader | None = None,
    entrypoint: str = "app",
) -> Analyzer:
    """사건 분석 에이전트. 검색기·선택적 센서 조회기(#105)는 조립자가 넘긴다.

    sensor_reader 생략 시 기존 사건 원본 분석, 주입 시 구간 조회·수치 검증을 제공한다.
    """
    from weeing_weeing.agent.analyst import IncidentAnalyzer
    from weeing_weeing.config import get_settings

    settings = settings or get_settings()
    return IncidentAnalyzer(
        client or get_llm_client(settings, entrypoint=entrypoint),
        retriever,
        timeout_s=settings.llm_timeout_s,
        max_turns=settings.agent_max_turns,
        sensor_reader=sensor_reader,
    )
