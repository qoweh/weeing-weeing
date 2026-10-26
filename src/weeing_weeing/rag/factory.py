"""설정을 읽어 저장소를 한 번만 조립한다. 색인 스크립트와 API 서버가 시작할 때 부른다.

    store = build_store(get_settings())
      ├ VECTOR_STORE=qdrant → QdrantVectorStore(QDRANT_URL 서버 또는 QDRANT_PATH 로컬)
      │              chroma → ChromaVectorStore(CHROMA_DIR, 텔레메트리 끔)
      ├ embedder = #6 create_embeddings(EMBEDDING_MODEL)
      └ sparse   = KiwiBm25Encoder()

벡터 DB에는 벡터만 남고 모델은 저장되지 않는다. 그래서 색인과 검색 모두 모델이
메모리에 올라와 있어야 하고, 프로세스마다 build_store를 한 번 불러 재사용한다.
"""

from collections.abc import Callable

from weeing_weeing.config import Settings
from weeing_weeing.rag.interface import Indexer
from weeing_weeing.rag.sparse import KiwiBm25Encoder, SparseEncoder
from weeing_weeing.rag.store import Embedder, VectorStore


class StoreConfigError(ValueError):
    """설정이 비었거나 잘못됐다."""


class StoreLockedError(RuntimeError):
    """로컬 저장소 폴더를 다른 프로세스가 쓰고 있다."""


def _qdrant_client(settings: Settings):
    from qdrant_client import QdrantClient

    if settings.qdrant_url:  # 서버 모드
        return QdrantClient(url=settings.qdrant_url, timeout=settings.qdrant_timeout_s)
    settings.qdrant_path.mkdir(parents=True, exist_ok=True)
    try:  # 로컬 모드: 한 폴더를 한 프로세스만 연다
        return QdrantClient(path=str(settings.qdrant_path))
    except RuntimeError as exc:
        if "already accessed" not in str(exc):
            raise
        raise StoreLockedError(
            f"{settings.qdrant_path}를 다른 프로세스(API 서버 등)가 사용 중이다. "
            "그 프로세스를 끄거나 QDRANT_URL 서버 모드를 쓴다"
        ) from exc


def _chroma_client(settings: Settings):
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    # 기본값이 텔레메트리 켜짐이라 설비 데이터 외부 반출 금지 원칙에 맞게 끈다.
    return chromadb.PersistentClient(
        path=str(settings.chroma_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _default_embedder(model_name: str) -> Embedder:
    # 모델 로드에 수 초·수 GB가 들어서 필요할 때만 import한다.
    from weeing_weeing.rag.embedder import EmbeddingConfig, create_embeddings

    return create_embeddings(EmbeddingConfig(model_name=model_name))


class LazyEmbedder:
    """첫 임베딩 때 모델을 한 번 올린다.

    저장소 조립·설정 검사·dry-run은 모델 없이 끝나고, 실제로 임베딩할 때만 비용을 낸다.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Embedder | None = None

    def _get(self) -> Embedder:
        if self._model is None:
            self._model = _default_embedder(self.model_name)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._get().embed_query(text)


def build_store(
    settings: Settings,
    *,
    embedder: Embedder | None = None,
    sparse_encoder: SparseEncoder | None = None,
    recreate: bool = False,
) -> VectorStore:
    """embedder·sparse_encoder를 주면 그것을 쓴다(테스트). recreate는 컬렉션을 새로 만든다."""
    if not settings.embedding_model.strip():
        raise StoreConfigError(
            "EMBEDDING_MODEL이 비어 있다. .env에 임베딩 모델 이름을 적는다(예: BAAI/bge-m3)"
        )
    kwargs = dict(
        embedder=embedder or LazyEmbedder(settings.embedding_model),
        embedding_model=settings.embedding_model,
        sparse_encoder=sparse_encoder or KiwiBm25Encoder(),
        collection=settings.rag_collection,
        recreate=recreate,
    )
    if settings.vector_store == "qdrant":
        from weeing_weeing.rag.qdrant_store import QdrantVectorStore

        return QdrantVectorStore(_qdrant_client(settings), **kwargs)
    if settings.vector_store == "chroma":
        from weeing_weeing.rag.chroma_store import ChromaVectorStore

        return ChromaVectorStore(_chroma_client(settings), **kwargs)
    raise StoreConfigError(
        f"VECTOR_STORE={settings.vector_store!r}: qdrant 또는 chroma만 쓸 수 있다"
    )


def indexer_class() -> Callable[[VectorStore], Indexer]:
    """문서 파싱·청킹 Indexer(#6) 연결 자리. store를 받아 Indexer를 만드는 것을 돌려준다.

    색인 명령은 저장소를 열기 전에 이 함수로 Indexer가 있는지 먼저 확인한다
    (--recreate가 컬렉션을 지운 뒤에 Indexer가 없다고 멈추지 않게).
    """
    raise NotImplementedError(
        "#6 Indexer(파싱·청킹 → Chunk)가 아직 없다. 계획만 보려면 --dry-run을 쓴다"
    )


def build_indexer(store: VectorStore) -> Indexer:
    return indexer_class()(store)
