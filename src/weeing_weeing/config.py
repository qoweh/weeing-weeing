"""환경변수 설정. 항목과 기본값은 .env.example과 같게 유지한다."""

import os
from dataclasses import dataclass, field
from pathlib import Path

# 상대 경로 설정(UPLOAD_DIR 등)은 실행 위치가 아니라 레포 루트 기준으로 푼다.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def from_root(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    llm_model: str  # Claude 모델 ID. API 키는 SDK가 ANTHROPIC_API_KEY에서 직접 읽는다
    llm_effort: str  # 생각 깊이: low | medium | high | xhigh | max
    llm_timeout_s: float  # API 호출 한 번의 제한 시간
    agent_max_turns: int  # 사건 하나 분석에서 LLM 호출 상한
    embedding_model: str  # 비어 있으면 공급자 기본 모델(rag/embedder.py DEFAULT_MODELS)
    vector_store: str  # qdrant | chroma
    rag_collection: str
    upload_dir: Path  # 업로드 문서(git 밖)
    qdrant_path: Path
    qdrant_url: str  # 비어 있으면 로컬 모드(qdrant_path)
    qdrant_timeout_s: float
    chroma_dir: Path
    database_url: str  # postgresql://… 또는 개발용 sqlite:///storage/dev.db
    db_timeout_s: float
    telemetry_csv: Path
    replay_speed: float
    telemetry_history_dir: Path = Path("outputs/incident_history")
    reranker_model: str = (
        ""  # 비어 있으면 리랭킹 끔(RRF 순위), 지정하면 Voyage 리랭크 API
    )
    # 임베딩 공급자(docs/EMBEDDING_API.md). hashing은 외부 호출·토큰 비용이 없다
    embedding_provider: str = "hashing"  # hashing | voyage
    embedding_dim: int = 1024  # voyage는 256·512·1024·2048
    # Voyage API. 키는 VOYAGE_API_KEY에서 직접 읽는다(설정 객체에 담지 않는다)
    voyage_base_url: str = "https://api.voyageai.com/v1"
    voyage_timeout_s: float = 30
    rag_candidate_k: int = 30  # 리랭킹할 최소 후보 수. 최종 k보다 작으면 k까지 확장
    auth_session_hours: float = 12  # 로그인 세션 유효 시간(교대 근무 한 번)
    rag_min_relevance: float | None = (
        None  # #75 실측 전에는 관련도 필터를 기본 적용하지 않음
    )
    # 사용량 기록(#113). 키는 SDK가 LANGFUSE_PUBLIC_KEY·LANGFUSE_SECRET_KEY에서 직접 읽는다
    llm_user: str = ""  # 사람별 집계 이름(GitHub 핸들)
    langfuse_base_url: str = ""  # 비어 있으면 기록하지 않는다
    langfuse_tracing_environment: str = "dev"  # dev | demo | ci
    langfuse_capture_content: bool = True  # 프롬프트·응답 본문까지 보낼지
    # 사용량 요약 조회(#207). 기록과 같은 키로 Langfuse Metrics API를 읽는다. 로그에 남지 않게 repr에서 뺀다
    langfuse_public_key: str = field(default="", repr=False)
    langfuse_secret_key: str = field(default="", repr=False)
    langfuse_dashboard_url: str = ""  # 비어 있으면 화면에 "자세히 보기" 링크를 숨긴다
    langfuse_query_timeout_s: float = 10
    # 챗봇 전용 LLM 설정(#216·#217). 비우면 LLM_MODEL·LLM_EFFORT를 그대로 쓴다
    chat_llm_effort: str = ""  # 챗봇 도구 루프 effort
    chat_review_model: str = ""  # 근거 검토 호출 모델(예: claude-haiku-5-5)
    chat_review_effort: str = ""  # 근거 검토 호출 effort(비우면 챗봇 effort)
    analysis_auto_enabled: bool = False  # 유료 자동 호출은 명시적으로 켠다
    analysis_mode: str = "single"  # single | multi
    analysis_verification_enabled: bool = False
    analysis_total_timeout_s: float = 180
    analysis_max_calls: int = 24
    telemetry_db_enabled: bool = False  # 분석 작업 없이 센서·사건만 저장
    telemetry_auth_required: bool = False  # 운영 compose는 항상 true
    telemetry_producer_token_sha256: str = ""  # 원본 토큰 대신 SHA-256만 보관
    telemetry_simulation_rpm_enabled: bool = False  # loopback RPM 시나리오 시험만
    telemetry_unreal_context_enabled: bool = False  # 명시적 시뮬레이터 상태 프레임 수신
    ml_prediction_enabled: bool = False
    ml_model_path: Path = Path("models/future_error.joblib")
    ml_model_sha256: str = ""
    ml_prediction_dir: Path = Path("outputs/ml_live")


def get_settings() -> Settings:
    env = os.environ.get
    min_relevance = env("RAG_MIN_RELEVANCE", "").strip()
    return Settings(
        llm_model=env("LLM_MODEL", "claude-sonnet-5-5"),
        llm_effort=env("LLM_EFFORT", "medium"),
        llm_timeout_s=float(env("LLM_TIMEOUT_S", "120")),
        agent_max_turns=int(env("AGENT_MAX_TURNS", "8")),
        embedding_model=env("EMBEDDING_MODEL", ""),
        embedding_provider=env("EMBEDDING_PROVIDER", "hashing").strip().lower(),
        embedding_dim=int(env("EMBEDDING_DIM", "1024")),
        voyage_base_url=env("VOYAGE_BASE_URL", "https://api.voyageai.com/v1").strip(),
        voyage_timeout_s=float(env("VOYAGE_TIMEOUT_S", "30")),
        vector_store=env("VECTOR_STORE", "qdrant"),
        rag_collection=env("RAG_COLLECTION", "knowledge_voyage").strip(),
        upload_dir=Path(env("UPLOAD_DIR", "storage/uploads")),
        qdrant_path=Path(env("QDRANT_PATH", "storage/qdrant")),
        qdrant_url=env("QDRANT_URL", ""),
        qdrant_timeout_s=float(env("QDRANT_TIMEOUT_S", "10")),
        chroma_dir=Path(env("CHROMA_DIR", "storage/chroma")),
        database_url=env(
            "DATABASE_URL", "postgresql://weeing:weeing@localhost:5432/weeing"
        ),
        db_timeout_s=float(env("DB_TIMEOUT_S", "5")),
        telemetry_csv=Path(
            env(
                "TELEMETRY_CSV",
                "data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv",
            )
        ),
        replay_speed=float(env("REPLAY_SPEED", "1.0")),
        telemetry_history_dir=Path(
            env("TELEMETRY_HISTORY_DIR", "outputs/incident_history")
        ),
        reranker_model=env("RERANKER_MODEL", ""),
        rag_candidate_k=int(env("RAG_CANDIDATE_K", "30")),
        rag_min_relevance=float(min_relevance) if min_relevance else None,
        auth_session_hours=float(env("AUTH_SESSION_HOURS", "12")),
        llm_user=env("LLM_USER", ""),
        langfuse_base_url=env("LANGFUSE_BASE_URL", ""),
        langfuse_tracing_environment=env("LANGFUSE_TRACING_ENVIRONMENT", "dev"),
        langfuse_public_key=env("LANGFUSE_PUBLIC_KEY", "").strip(),
        langfuse_secret_key=env("LANGFUSE_SECRET_KEY", "").strip(),
        langfuse_dashboard_url=env("LANGFUSE_DASHBOARD_URL", "").strip(),
        langfuse_query_timeout_s=float(env("LANGFUSE_QUERY_TIMEOUT_S", "10")),
        chat_llm_effort=env("CHAT_LLM_EFFORT", "").strip().lower(),
        chat_review_model=env("CHAT_REVIEW_MODEL", "").strip(),
        chat_review_effort=env("CHAT_REVIEW_EFFORT", "").strip().lower(),
        langfuse_capture_content=env("LANGFUSE_CAPTURE_CONTENT", "true").lower()
        in ("1", "true", "yes"),
        analysis_auto_enabled=env("ANALYSIS_AUTO_ENABLED", "false").lower()
        in ("1", "true", "yes"),
        analysis_mode=env("ANALYSIS_MODE", "single").strip().lower(),
        analysis_verification_enabled=env(
            "ANALYSIS_VERIFICATION_ENABLED", "false"
        ).lower()
        in ("1", "true", "yes"),
        analysis_total_timeout_s=float(env("ANALYSIS_TOTAL_TIMEOUT_S", "180")),
        analysis_max_calls=int(env("ANALYSIS_MAX_CALLS", "24")),
        telemetry_db_enabled=env("TELEMETRY_DB_ENABLED", "false").lower()
        in ("1", "true", "yes"),
        telemetry_auth_required=env("TELEMETRY_AUTH_REQUIRED", "false").lower()
        in ("1", "true", "yes"),
        telemetry_producer_token_sha256=env("TELEMETRY_PRODUCER_TOKEN_SHA256", ""),
        telemetry_simulation_rpm_enabled=env(
            "TELEMETRY_SIMULATION_RPM_ENABLED", "false"
        ).lower()
        in ("1", "true", "yes"),
        ml_prediction_enabled=env("ML_PREDICTION_ENABLED", "false").lower()
        in ("1", "true", "yes"),
        ml_model_path=Path(env("ML_MODEL_PATH", "models/future_error.joblib")),
        ml_model_sha256=env("ML_MODEL_SHA256", "").strip().lower(),
        ml_prediction_dir=Path(env("ML_PREDICTION_DIR", "outputs/ml_live")),
        telemetry_unreal_context_enabled=env(
            "TELEMETRY_UNREAL_CONTEXT_ENABLED", "false"
        ).lower()
        in ("1", "true", "yes"),
    )
