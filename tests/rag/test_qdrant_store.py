"""Qdrant 구현만의 동작. 공용 시나리오는 test_store_contract.py."""

import uuid

import pytest
from fakes import FakeEmbedder
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from test_store_contract import manual_chunks

from weeing_weeing.rag.qdrant_store import QdrantVectorStore, point_id, to_filter
from weeing_weeing.rag.sparse import KiwiBm25Encoder
from weeing_weeing.rag.store import STORE_SCHEMA, StoreMismatchError


def make(client, **kwargs):
    kwargs.setdefault("embedder", FakeEmbedder())
    kwargs.setdefault("embedding_model", "fake-embedder-v1")
    return QdrantVectorStore(client, **kwargs)


def test_point_id_is_stable_uuid():
    pid = point_id("BTT-MANUAL:2.0:0001")
    assert pid == point_id("BTT-MANUAL:2.0:0001")
    assert pid != point_id("BTT-MANUAL:2.0:0002")
    assert uuid.UUID(pid).version == 5


def test_collection_has_cosine_dense_sparse_idf_and_metadata():
    client = QdrantClient(":memory:")
    make(client).replace_document("BTT-MANUAL", manual_chunks())

    config = client.get_collection("knowledge_voyage").config
    assert config.params.vectors["dense"].distance == qm.Distance.COSINE
    assert config.params.vectors["dense"].size == 64
    assert config.params.sparse_vectors["sparse"].modifier == qm.Modifier.IDF
    assert config.metadata == {
        "embedding_model": "fake-embedder-v1",
        "store_schema": STORE_SCHEMA,
        "dim": 64,
    }


def test_local_path_persists_after_reopen(tmp_path):
    path = str(tmp_path / "qdrant")
    client = QdrantClient(path=path)
    make(client).replace_document("BTT-MANUAL", manual_chunks())
    client.close()

    reopened = QdrantClient(path=path)
    assert len(make(reopened).chunks()) == 3
    with pytest.raises(StoreMismatchError, match="embedding_model"):
        make(reopened, embedding_model="other-model")
    reopened.close()


def test_local_path_allows_only_one_client(tmp_path):
    path = str(tmp_path / "qdrant")
    client = QdrantClient(path=path)
    with pytest.raises(RuntimeError, match="already accessed"):
        QdrantClient(path=path)
    client.close()


def test_other_dimension_is_rejected_before_deleting():
    client = QdrantClient(":memory:")
    make(client).replace_document("BTT-MANUAL", manual_chunks())

    with pytest.raises(StoreMismatchError, match="dim"):
        make(client, embedder=FakeEmbedder(dim=32)).replace_document(
            "BTT-MANUAL", manual_chunks("2.1")
        )
    assert len(make(client).chunks()) == 3


def test_recreate_drops_existing_collection():
    client = QdrantClient(":memory:")
    make(client).replace_document("BTT-MANUAL", manual_chunks())

    store = make(client, embedding_model="new-model", recreate=True)
    assert store.chunks() == []
    store.replace_document("BTT-MANUAL", manual_chunks())
    assert client.get_collection("knowledge_voyage").config.metadata[
        "embedding_model"
    ] == ("new-model")


def test_where_translation():
    flt = to_filter({"doc_type": "manual", "codes": ["BTT2-P01", "BTT2-P03"]})
    assert flt == qm.Filter(
        must=[
            qm.FieldCondition(key="doc_type", match=qm.MatchValue(value="manual")),
            qm.FieldCondition(
                key="codes", match=qm.MatchAny(any=["BTT2-P01", "BTT2-P03"])
            ),
        ]
    )
    assert to_filter(None) is None
    assert to_filter({}) is None


def test_sparse_encoder_name_is_recorded_and_points_have_sparse_vectors():
    client = QdrantClient(":memory:")
    make(client, sparse_encoder=KiwiBm25Encoder()).replace_document(
        "BTT-MANUAL", manual_chunks()
    )

    assert client.get_collection("knowledge_voyage").config.metadata[
        "sparse_encoder"
    ] == (KiwiBm25Encoder.NAME)
    (record,), _ = client.scroll("knowledge_voyage", limit=1, with_vectors=True)
    assert set(record.vector) == {"dense", "sparse"}


def test_hybrid_needs_sparse_encoder():
    store = make(QdrantClient(":memory:"))
    with pytest.raises(RuntimeError, match="sparse_encoder"):
        store.hybrid_query("이송")


def test_write_interrupted_midway_is_marked_incomplete(monkeypatch):
    """새 청크를 쓰다 끊기면 옛·새가 섞이지만, documents()가 그것을 알려 준다."""
    client = QdrantClient(":memory:")
    make(client).replace_document("BTT-MANUAL", manual_chunks())
    assert make(client).documents()["BTT-MANUAL"].complete

    real_upsert = client.upsert
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise TimeoutError("서버 응답 없음(테스트)")
        return real_upsert(*args, **kwargs)

    monkeypatch.setattr(client, "upsert", flaky)
    changed = manual_chunks(sha="sha-manual-2")
    with pytest.raises(TimeoutError):
        make(client, batch_size=1).replace_document("BTT-MANUAL", changed)

    info = make(client).documents()["BTT-MANUAL"]
    assert info.complete is False  # 1개만 새 sha, 2개는 옛 sha
    monkeypatch.setattr(client, "upsert", real_upsert)
    make(client).replace_document("BTT-MANUAL", changed)
    assert make(client).documents()["BTT-MANUAL"].complete


def test_shorter_new_version_removes_leftover_chunks():
    client = QdrantClient(":memory:")
    make(client).replace_document("BTT-MANUAL", manual_chunks())
    make(client).replace_document("BTT-MANUAL", manual_chunks(texts=["하나만"]))

    assert [c.chunk_id for c in make(client).chunks()] == ["BTT-MANUAL:2.0:0000"]
