"""환경변수 설정. 항목과 기본값은 .env.example과 같게 유지한다."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str
    ollama_model: str
    llm_timeout_s: float
    embedding_model: str
    vector_store: str  # qdrant | chroma
    rag_collection: str
    qdrant_path: Path
    qdrant_url: str  # 비어 있으면 로컬 모드(qdrant_path)
    qdrant_timeout_s: float
    chroma_dir: Path
    database_url: str
    telemetry_csv: Path
    replay_speed: float


def get_settings() -> Settings:
    env = os.environ.get
    return Settings(
        ollama_base_url=env("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=env("OLLAMA_MODEL", ""),
        llm_timeout_s=float(env("LLM_TIMEOUT_S", "60")),
        embedding_model=env("EMBEDDING_MODEL", ""),
        vector_store=env("VECTOR_STORE", "qdrant"),
        rag_collection=env("RAG_COLLECTION", "knowledge"),
        qdrant_path=Path(env("QDRANT_PATH", "storage/qdrant")),
        qdrant_url=env("QDRANT_URL", ""),
        qdrant_timeout_s=float(env("QDRANT_TIMEOUT_S", "10")),
        chroma_dir=Path(env("CHROMA_DIR", "storage/chroma")),
        database_url=env(
            "DATABASE_URL", "postgresql://weeing:weeing@localhost:5432/weeing"
        ),
        telemetry_csv=Path(
            env(
                "TELEMETRY_CSV",
                "data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv",
            )
        ),
        replay_speed=float(env("REPLAY_SPEED", "1.0")),
    )
