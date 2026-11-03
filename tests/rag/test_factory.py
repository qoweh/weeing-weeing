"""저장소·색인기·검색기 조립."""

import dataclasses
from pathlib import Path

import pytest
from fakes import FakeEmbedder, TextIndexer

from weeing_weeing.config import get_settings
from weeing_weeing.rag import factory
from weeing_weeing.rag.chroma_store import ChromaVectorStore
from weeing_weeing.rag.qdrant_store import QdrantVectorStore
from weeing_weeing.rag.sparse import KiwiBm25Encoder
from weeing_weeing.rag.store import Chunk

ROOT = Path(__file__).resolve().parents[2]


def no_indexer():
    """Indexer 구현이 연결되지 않은 상태를 흉내 낸다(색인 명령이 저장소를 열기 전에 멈춰야 함)."""
    raise NotImplementedError("#6 Indexer가 아직 없다")


def settings(tmp_path, **overrides):
    base = get_settings()
    values = dict(
        embedding_model="fake-embedder-v1",
        vector_store="qdrant",
        qdrant_path=tmp_path / "qdrant",
        qdrant_url="",
        chroma_dir=tmp_path / "chroma",
        upload_dir=tmp_path / "uploads",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )
    return dataclasses.replace(base, **{**values, **overrides})


def test_qdrant_local_by_default(tmp_path):
    store = factory.build_store(settings(tmp_path), embedder=FakeEmbedder())

    assert isinstance(store, QdrantVectorStore)
    assert store._client.init_options["path"] == str(tmp_path / "qdrant")
    assert isinstance(store._sparse, KiwiBm25Encoder)
    store._client.close()


def test_chroma_with_telemetry_off(tmp_path):
    store = factory.build_store(
        settings(tmp_path, vector_store="chroma"), embedder=FakeEmbedder()
    )

    assert isinstance(store, ChromaVectorStore)
    assert store._client.get_settings().anonymized_telemetry is False
    store.close()


def test_chroma_factory_releases_client_on_constructor_failure(tmp_path, monkeypatch):
    configured = settings(tmp_path, vector_store="chroma")
    first = factory.build_store(configured, embedder=FakeEmbedder())
    first.replace_document("A", [Chunk("A:1:0000", "A", "1", "probe", {})])
    real_client = factory._chroma_client
    closed = []

    def tracked_client(settings):
        client = real_client(settings)
        close = client.close

        def tracked_close():
            closed.append(1)
            close()

        monkeypatch.setattr(client, "close", tracked_close)
        return client

    monkeypatch.setattr(factory, "_chroma_client", tracked_client)
    try:
        from weeing_weeing.rag.store import StoreMismatchError

        with pytest.raises(StoreMismatchError):
            factory.build_store(
                dataclasses.replace(configured, embedding_model="other-model"),
                embedder=FakeEmbedder(),
            )
        assert closed == [1]
        assert first.query("probe")
    finally:
        first.close()


def test_qdrant_server_mode_uses_url_and_timeout(tmp_path, monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def collection_exists(self, name):
            return False

    monkeypatch.setattr("qdrant_client.QdrantClient", FakeClient)
    factory.build_store(
        settings(tmp_path, qdrant_url="http://qdrant:6333", qdrant_timeout_s=3.0),
        embedder=FakeEmbedder(),
    )
    assert seen == {"url": "http://qdrant:6333", "timeout": 3.0}


def test_unknown_embedding_provider_is_clear_error(tmp_path):
    with pytest.raises(factory.StoreConfigError, match="EMBEDDING_PROVIDER"):
        factory.build_store(settings(tmp_path, embedding_provider="bge-local"))


def test_voyage_dimension_is_validated(tmp_path):
    with pytest.raises(factory.StoreConfigError, match="EMBEDDING_DIM"):
        factory.build_store(
            settings(tmp_path, embedding_provider="voyage", embedding_dim=300)
        )


@pytest.mark.parametrize(
    ("provider", "model", "dim", "expected"),
    [
        ("hashing", "", 1024, "hashing:hashing-kiwi-v1:1024"),
        ("voyage", "", 512, "voyage:voyage-4-lite:512"),
        ("voyage", "voyage-4", 1024, "voyage:voyage-4:1024"),
    ],
)
def test_collection_name_records_provider_model_and_dim(
    tmp_path, provider, model, dim, expected
):
    configured = settings(
        tmp_path, embedding_provider=provider, embedding_model=model, embedding_dim=dim
    )
    assert factory.collection_embedding_name(configured) == expected


def test_voyage_embedder_uses_configured_endpoint(tmp_path):
    from weeing_weeing.rag.embedder import VoyageEmbedder

    embedder = factory.build_embedder(
        settings(
            tmp_path,
            embedding_provider="voyage",
            embedding_model="",
            embedding_dim=256,
            voyage_base_url="https://example.test/v1",
            voyage_timeout_s=7.0,
        )
    )
    assert isinstance(embedder, VoyageEmbedder)
    assert (embedder.model, embedder.dim) == ("voyage-4-lite", 256)
    assert embedder._base_url == "https://example.test/v1"
    assert embedder._timeout_s == 7.0


def test_unknown_backend_is_rejected(tmp_path):
    with pytest.raises(factory.StoreConfigError, match="VECTOR_STORE='milvus'"):
        factory.build_store(
            settings(tmp_path, vector_store="milvus"), embedder=FakeEmbedder()
        )


def test_locked_local_folder_explains_fix(tmp_path):
    first = factory.build_store(settings(tmp_path), embedder=FakeEmbedder())

    with pytest.raises(factory.StoreLockedError, match="QDRANT_URL 서버 모드"):
        factory.build_store(settings(tmp_path), embedder=FakeEmbedder())
    first._client.close()


def test_default_is_hashing_embedder_without_external_calls(tmp_path, monkeypatch):
    """기본 설정은 로컬 모델·외부 API 없이 색인·검색까지 된다(토큰 비용 0)."""
    import httpx

    from weeing_weeing.rag.embedder import HashingEmbedder

    def no_network(*args, **kwargs):
        raise AssertionError("기본 설정에서 외부 API를 호출하면 안 된다")

    monkeypatch.setattr(httpx.Client, "post", no_network)
    configured = settings(tmp_path, vector_store="chroma", embedding_model="")
    assert isinstance(factory.build_embedder(configured), HashingEmbedder)
    store = factory.build_store(configured)
    try:
        store.replace_document(
            "A",
            [
                Chunk("A:1:0000", "A", "1", "입구 광전센서 차단 점검", {}),
                Chunk("A:1:0001", "A", "1", "모터 베어링 진동 점검", {}),
            ],
        )
        assert store.query("광전센서", k=1)[0].chunk.chunk_id == "A:1:0000"
        assert store.hybrid_query("베어링", k=1)[0].chunk.chunk_id == "A:1:0001"
    finally:
        store.close()


def test_build_indexer_uses_indexer_class(monkeypatch):
    monkeypatch.setattr(factory, "indexer_class", lambda: TextIndexer)
    store = object()
    assert factory.build_indexer(store).store is store


def test_real_indexer_is_connected():
    from weeing_weeing.rag.indexer import DocumentIndexer

    assert factory.indexer_class() is DocumentIndexer


def test_build_retriever_uses_configured_reranker(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from weeing_weeing.rag import reranker
    from weeing_weeing.rag.store import Hit

    post = Mock(
        return_value={
            "data": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.1},
            ]
        }
    )
    monkeypatch.setattr(reranker, "voyage_post", post)
    store = Mock()
    store.hybrid_query.return_value = [
        Hit(Chunk(f"MAN:1:{i:04d}", "MAN", "1", text), 0.03 - i * 0.01)
        for i, text in enumerate(["모터 점검", "광전 센서 점검"])
    ]
    retriever = factory.build_retriever(
        settings(
            tmp_path,
            reranker_model="rerank-3-lite",
            rag_candidate_k=12,
            rag_min_relevance=0.5,
        ),
        store,
    )
    post.assert_not_called()
    found = retriever.search("센서", k=2)
    assert len(found) == 1
    assert found[0].text == "광전 센서 점검"
    assert found[0].relevance == 0.9
    store.hybrid_query.assert_called_once_with("센서", k=12, where=None)
    assert post.call_args.args[1]["model"] == "rerank-3-lite"


def test_empty_reranker_model_turns_reranking_off(tmp_path):
    assert factory.build_reranker(settings(tmp_path, reranker_model="")) is None
    assert factory.build_reranker(settings(tmp_path, reranker_model="  ")) is None


def test_factory_rejects_relevance_filter_without_reranker(tmp_path):
    with pytest.raises(ValueError, match="리랭커가 필요"):
        factory.build_retriever(
            settings(tmp_path, reranker_model="", rag_min_relevance=0.5), None
        )


def test_public_indexer_and_retriever_share_one_store(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from weeing_weeing.rag import interface

    store = Mock()
    store.hybrid_query.return_value = []
    build_store = Mock(return_value=store)
    monkeypatch.setattr(factory, "build_store", build_store)
    monkeypatch.setenv("RERANKER_MODEL", "")
    interface.get_indexer.cache_clear()
    interface.get_retriever.cache_clear()
    interface._get_store.cache_clear()
    try:
        indexer = interface.get_indexer()
        retriever = interface.get_retriever()
        assert interface.get_indexer() is indexer
        assert interface.get_retriever() is retriever
        assert retriever.search("센서") == []
        build_store.assert_called_once()
        store.hybrid_query.assert_called_once_with("센서", k=5, where=None)
    finally:
        interface.get_indexer.cache_clear()
        interface.get_retriever.cache_clear()
        interface._get_store.cache_clear()


# --- DB(document 테이블)와 함께 ---


def _db(cli):
    from weeing_weeing.db.interface import open_documents

    return open_documents(cli.db_url)
