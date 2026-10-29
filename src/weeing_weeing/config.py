"""환경변수 설정. 항목과 기본값은 .env.example과 같게 유지한다."""

import os
from dataclasses import dataclass
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
    embedding_model: str
    vector_store: str  # qdrant | chroma
    rag_collection: str
    rag_catalog: Path  # git이 관리하는 기준 문서 목록
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
    reranker_model: str = ""  # 비어 있으면 RRF 순위, 지정하면 로컬 CrossEncoder
    rag_candidate_k: int = 30  # 리랭킹할 최소 후보 수. 최종 k보다 작으면 k까지 확장
    auth_session_hours: float = 12  # 로그인 세션 유효 시간(교대 근무 한 번)


def get_settings() -> Settings:
    env = os.environ.get
    return Settings(
        llm_model=env("LLM_MODEL", "claude-opus-5-5"),
        llm_effort=env("LLM_EFFORT", "medium"),
        llm_timeout_s=float(env("LLM_TIMEOUT_S", "120")),
        agent_max_turns=int(env("AGENT_MAX_TURNS", "8")),
        embedding_model=env("EMBEDDING_MODEL", "BAAI/bge-m3"),
        vector_store=env("VECTOR_STORE", "qdrant"),
        rag_collection=env("RAG_COLLECTION", "knowledge"),
        rag_catalog=Path(env("RAG_CATALOG", "data/catalog.toml")),
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
        reranker_model=env("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        rag_candidate_k=int(env("RAG_CANDIDATE_K", "30")),
        auth_session_hours=float(env("AUTH_SESSION_HOURS", "12")),
    )
