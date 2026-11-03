"""설정을 읽어 저장소를 한 번만 조립한다. 색인 스크립트와 API 서버가 시작할 때 부른다.

    store = build_store(get_settings())
      ├ VECTOR_STORE=qdrant → QdrantVectorStore(QDRANT_URL 서버 또는 QDRANT_PATH 로컬)
      │              chroma → ChromaVectorStore(CHROMA_DIR, 텔레메트리 끔)
      ├ embedder = build_embedder: EMBEDDING_PROVIDER=hashing(기본, 비용 0) 또는 voyage(API)
      └ sparse   = KiwiBm25Encoder()

로컬 모델 가중치는 쓰지 않는다. 색인과 검색은 같은 임베더(같은 공급자·모델·차원)를
써야 하므로 컬렉션에 "공급자:모델:차원"을 기록하고, 프로세스마다 build_store를 한 번 불러 재사용한다.
"""

from collections.abc import Callable

from weeing_weeing.config import Settings
from weeing_weeing.rag.interface import Indexer
from weeing_weeing.rag.reranker import Reranker, VoyageReranker
from weeing_weeing.rag.retriever import HybridRetriever
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


def embedding_spec(settings: Settings) -> tuple[str, str, int]:
    """설정에서 (공급자, 모델, 차원)을 정한다. 잘못된 값은 StoreConfigError."""
    from weeing_weeing.rag.embedder import DEFAULT_MODELS, PROVIDERS, VOYAGE_DIMS

    provider = settings.embedding_provider.strip().lower()
    if provider not in PROVIDERS:
        raise StoreConfigError(
            f"EMBEDDING_PROVIDER={settings.embedding_provider!r}: "
            f"{' 또는 '.join(PROVIDERS)}만 쓸 수 있다"
        )
    model = settings.embedding_model.strip() or DEFAULT_MODELS[provider]
    dim = settings.embedding_dim
    if provider == "voyage" and dim not in VOYAGE_DIMS:
        raise StoreConfigError(f"EMBEDDING_DIM={dim}: voyage는 {VOYAGE_DIMS} 중 하나")
    if dim < 8:
        raise StoreConfigError(f"EMBEDDING_DIM={dim}: 8 이상이어야 한다")
    return provider, model, dim


def _default_embedder(settings: Settings) -> Embedder:
    from weeing_weeing.rag.embedder import HashingEmbedder, VoyageEmbedder

    provider, model, dim = embedding_spec(settings)
    if provider == "voyage":
        return VoyageEmbedder(
            model,
            dim=dim,
            base_url=settings.voyage_base_url,
            timeout_s=settings.voyage_timeout_s,
        )
    return HashingEmbedder(dim)


def build_embedder(settings: Settings) -> Embedder:
    """설정의 임베더. 외부 호출·형태소 분석기 로드는 첫 임베딩 때 일어난다."""
    return _default_embedder(settings)


def collection_embedding_name(settings: Settings) -> str:
    """컬렉션에 기록하는 임베딩 이름. 예: "hashing:hashing-kiwi-v1:1024"."""
    from weeing_weeing.rag.embedder import collection_model_name

    return collection_model_name(*embedding_spec(settings))


def build_store(
    settings: Settings,
    *,
    embedder: Embedder | None = None,
    sparse_encoder: SparseEncoder | None = None,
    recreate: bool = False,
) -> VectorStore:
    """embedder·sparse_encoder를 주면 그것을 쓴다(테스트). recreate는 컬렉션을 새로 만든다."""
    kwargs = dict(
        embedder=embedder or build_embedder(settings),
        embedding_model=collection_embedding_name(settings),
        sparse_encoder=sparse_encoder or KiwiBm25Encoder(),
        collection=settings.rag_collection,
        recreate=recreate,
    )
    if settings.vector_store == "qdrant":
        from weeing_weeing.rag.qdrant_store import QdrantVectorStore

        return QdrantVectorStore(_qdrant_client(settings), **kwargs)
    if settings.vector_store == "chroma":
        from weeing_weeing.rag.chroma_store import ChromaVectorStore

        client = _chroma_client(settings)
        try:
            return ChromaVectorStore(client, owns_client=True, **kwargs)
        except Exception:
            # Failed construction must not retain a reference to a persistent
            # system and keep its files locked after other clients close.
            client.close()
            raise
    raise StoreConfigError(
        f"VECTOR_STORE={settings.vector_store!r}: qdrant 또는 chroma만 쓸 수 있다"
    )


def indexer_class() -> Callable[[VectorStore], Indexer]:
    """문서 파싱·청킹 Indexer. store를 받아 Indexer를 만드는 것을 돌려준다.

    웹 업로드와 격리된 검색 평가에서 같은 구현체를 사용한다.
    """
    from weeing_weeing.rag.indexer import DocumentIndexer

    return DocumentIndexer


def build_indexer(store: VectorStore) -> Indexer:
    return indexer_class()(store)


def build_reranker(settings: Settings, *, batch_size: int = 100) -> Reranker | None:
    """RERANKER_MODEL을 지정한 경우에만 Voyage 리랭커를 만든다. 비어 있으면 끈다(비용 0)."""
    if not settings.reranker_model.strip():
        return None
    return VoyageReranker(
        settings.reranker_model,
        batch_size=batch_size,
        base_url=settings.voyage_base_url,
        timeout_s=settings.voyage_timeout_s,
    )


def build_retriever(
    settings: Settings, store: VectorStore, *, reranker: Reranker | None = None
) -> HybridRetriever:
    """색인된 저장소에 검색을 연결한다. 저장소의 소유·종료는 호출자가 담당한다."""
    return HybridRetriever(
        store,
        reranker=reranker if reranker is not None else build_reranker(settings),
        candidate_k=settings.rag_candidate_k,
        min_relevance=settings.rag_min_relevance,
    )
