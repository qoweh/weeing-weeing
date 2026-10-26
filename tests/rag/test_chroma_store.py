"""Chroma 구현만의 동작. 공용 시나리오는 test_store_contract.py."""

import chromadb
import pytest
from chromadb.config import Settings
from fakes import FakeEmbedder
from test_store_contract import manual_chunks

from weeing_weeing.rag.chroma_store import ChromaVectorStore, to_where
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

    col = client.get_collection("knowledge")
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
    col = client.get_collection("knowledge")
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
