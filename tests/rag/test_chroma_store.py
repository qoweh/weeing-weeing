"""Chroma 구현만의 동작. 공용 시나리오는 test_store_contract.py."""

import shutil

import chromadb
import pytest
from chromadb.config import Settings
from fakes import FakeEmbedder
from test_store_contract import manual_chunks, sop_chunks

from weeing_weeing.rag.chroma_store import ChromaVectorStore, to_where
from weeing_weeing.rag.sparse import KiwiBm25Encoder
from weeing_weeing.rag.store import STORE_SCHEMA, StoreMismatchError


@pytest.fixture
def client(tmp_path):
    return chromadb.PersistentClient(
        path=str(tmp_path / "chroma"), settings=Settings(anonymized_telemetry=False)
    )


def make(client, **kwargs):
    kwargs.setdefault("embedder", FakeEmbedder())
    kwargs.setdefault("embedding_model", "fake-embedder-v1")
    return ChromaVectorStore(client, **kwargs)


def test_collection_is_cosine_without_embedding_function(client):
    make(client).replace_document("BTT-MANUAL", manual_chunks())

    col = client.get_collection("knowledge_voyage")
    assert col.configuration["hnsw"]["space"] == "cosine"
    assert col.configuration["embedding_function"] is None
    assert col.metadata == {
        "embedding_model": "fake-embedder-v1",
        "store_schema": STORE_SCHEMA,
        "dim": 64,
    }


def test_score_is_one_minus_cosine_distance(client):
    store = make(client)
    store.replace_document("BTT-MANUAL", manual_chunks())

    hits = store.query(manual_chunks()[0].text, k=3)
    assert hits[0].score == pytest.approx(1.0, abs=1e-3)
    assert all(-1.0 - 1e-6 <= h.score <= 1.0 + 1e-6 for h in hits)


def test_persists_and_rejects_other_model(tmp_path):
    path = str(tmp_path / "chroma")
    settings = Settings(anonymized_telemetry=False)
    make(chromadb.PersistentClient(path=path, settings=settings)).replace_document(
        "BTT-MANUAL", manual_chunks()
    )

    reopened = chromadb.PersistentClient(path=path, settings=settings)
    assert len(make(reopened).chunks()) == 3
    with pytest.raises(StoreMismatchError, match="embedding_model"):
        make(reopened, embedding_model="other-model")


def test_other_dimension_is_rejected_before_deleting(client):
    make(client).replace_document("BTT-MANUAL", manual_chunks())

    with pytest.raises(StoreMismatchError, match="dim"):
        make(client, embedder=FakeEmbedder(dim=32)).replace_document(
            "BTT-MANUAL", manual_chunks("2.1")
        )
    assert len(make(client).chunks()) == 3


def test_recreate_drops_existing_collection(client):
    make(client).replace_document("BTT-MANUAL", manual_chunks())

    assert make(client, embedding_model="new-model", recreate=True).chunks() == []


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        (None, None),
        ({"doc_type": "manual"}, {"doc_type": "manual"}),
        ({"codes": "BTT2-P01"}, {"codes": {"$contains": "BTT2-P01"}}),
        (
            {"codes": ["BTT2-P01", "BTT2-P03"]},
            {
                "$or": [
                    {"codes": {"$contains": "BTT2-P01"}},
                    {"codes": {"$contains": "BTT2-P03"}},
                ]
            },
        ),
        ({"status": ["approved", "draft"]}, {"status": {"$in": ["approved", "draft"]}}),
        (
            {"doc_type": "manual", "codes": "BTT2-P01"},
            {"$and": [{"doc_type": "manual"}, {"codes": {"$contains": "BTT2-P01"}}]},
        ),
    ],
)
def test_where_translation(where, expected):
    assert to_where(where) == expected


def test_sparse_encoder_name_is_recorded(client):
    make(client, sparse_encoder=KiwiBm25Encoder()).replace_document(
        "BTT-MANUAL", manual_chunks()
    )
    assert client.get_collection("knowledge_voyage").metadata["sparse_encoder"] == (
        KiwiBm25Encoder.NAME
    )


def test_bm25_cache_follows_writes(client):
    store = make(client, sparse_encoder=KiwiBm25Encoder())
    store.replace_document("BTT-MANUAL", manual_chunks())
    store.replace_document("BTT-SOP-001", sop_chunks())
    assert store.hybrid_query("광전")  # 캐시 생성

    store.replace_document("BTT-MANUAL", manual_chunks("2.1", ["새로운 첨도 내용"]))
    hits = store.hybrid_query("첨도", k=10)
    assert hits[0].chunk.chunk_id == "BTT-MANUAL:2.1:0000"
    assert not any(":2.0:" in h.chunk.chunk_id for h in hits)  # 옛 청크가 안 나온다

    store.delete_document("BTT-MANUAL")
    hits = store.hybrid_query("첨도 격리", k=10)
    assert [h.chunk.doc_id for h in hits] == ["BTT-SOP-001"]  # 지운 문서가 안 나온다


def test_bm25_cache_follows_writes_from_another_store_object(client):
    """API 서버가 검색하는 동안 색인 명령(다른 객체)이 써도 KeyError·옛 내용이 없다."""
    reader = make(client, sparse_encoder=KiwiBm25Encoder())
    writer = make(client, sparse_encoder=KiwiBm25Encoder())
    writer.replace_document("BTT-SOP-001", sop_chunks())
    assert reader.hybrid_query("격리")  # reader 캐시 생성

    writer.replace_document("BTT-MANUAL", manual_chunks(texts=["첨도 상한 이탈 점검"]))
    hits = reader.hybrid_query("첨도", k=10)
    assert hits[0].chunk.chunk_id == "BTT-MANUAL:2.0:0000"

    writer.replace_document("BTT-MANUAL", manual_chunks(texts=["바뀐 첨도 설명"]))
    hits = reader.hybrid_query("첨도", k=1)
    assert hits[0].chunk.text == "바뀐 첨도 설명"


def test_large_document_is_written_in_batches(client, monkeypatch):
    """Chroma 최대 배치보다 청크가 많아도 나눠 쓰고, 기존 문서가 먼저 지워지지 않는다."""
    monkeypatch.setattr(client, "get_max_batch_size", lambda: 2)
    store = make(client)
    store.replace_document(
        "BTT-MANUAL", manual_chunks(texts=["가", "나", "다", "라", "마"])
    )

    info = store.documents()["BTT-MANUAL"]
    assert (info.chunk_count, info.complete) == (5, True)


def test_write_interrupted_midway_is_marked_incomplete(client, monkeypatch):
    store = make(client)
    store.replace_document("BTT-MANUAL", manual_chunks())
    monkeypatch.setattr(client, "get_max_batch_size", lambda: 1)
    col = client.get_collection("knowledge_voyage")
    real_update = type(col).update
    calls = []

    def flaky(self, **kwargs):  # 같은 ID라 update로 쓴다. 두 번째 배치에서 끊김
        calls.append(1)
        if len(calls) == 2:
            raise TimeoutError("쓰기 실패(테스트)")
        return real_update(self, **kwargs)

    monkeypatch.setattr(type(col), "update", flaky)
    with pytest.raises(TimeoutError):
        store.replace_document("BTT-MANUAL", manual_chunks(sha="sha-manual-2"))

    assert store.documents()["BTT-MANUAL"].complete is False
    assert store.documents()["BTT-MANUAL"].chunk_count == 3  # 문서가 비지 않았다


def test_borrowed_client_close_preserves_other_wrappers(client):
    reader, writer = make(client), make(client)
    writer.replace_document("BTT-MANUAL", manual_chunks())
    writer.close()
    writer.close()
    assert len(reader.chunks()) == 3
    assert len(writer.chunks()) == 3  # preserve existing borrowed-client behavior
    client.close()


def test_owned_client_close_is_idempotent_and_unlocks_files(tmp_path, monkeypatch):
    directory = tmp_path / "owned-chroma"
    assert directory.resolve().parent == tmp_path.resolve()
    client = chromadb.PersistentClient(
        path=str(directory), settings=Settings(anonymized_telemetry=False)
    )
    store = make(client, owns_client=True)
    store.replace_document("BTT-MANUAL", manual_chunks())
    calls = []
    close = client.close

    def tracked_close():
        calls.append(1)
        close()

    monkeypatch.setattr(client, "close", tracked_close)
    store.close()
    store.close()
    assert calls == [1]
    reopened = chromadb.PersistentClient(
        path=str(directory), settings=Settings(anonymized_telemetry=False)
    )
    try:
        assert len(make(reopened).chunks()) == 3  # closing is not deleting
    finally:
        reopened.close()
    assert directory.resolve().parent == tmp_path.resolve()
    shutil.rmtree(directory)  # Windows must release persistent file handles
    assert not directory.exists()


def test_closing_owned_client_keeps_separate_client_on_same_path(tmp_path):
    path = str(tmp_path / "shared-system")
    settings = Settings(anonymized_telemetry=False)
    first = make(
        chromadb.PersistentClient(path=path, settings=settings), owns_client=True
    )
    second = make(
        chromadb.PersistentClient(path=path, settings=settings), owns_client=True
    )
    try:
        first.replace_document("BTT-MANUAL", manual_chunks())
        first.close()
        assert len(second.chunks()) == 3
    finally:
        first.close()
        second.close()
