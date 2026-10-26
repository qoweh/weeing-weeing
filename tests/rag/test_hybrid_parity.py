"""두 백엔드가 같은 코퍼스에서 같은 순위를 내는지, Qdrant 안의 계산이 파이썬 식과 같은지."""

import conftest
import pytest
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from test_store_contract import hybrid_extra_chunks, manual_chunks, sop_chunks

from weeing_weeing.rag.qdrant_store import SPARSE
from weeing_weeing.rag.sparse import Bm25Index
from weeing_weeing.rag.store import rrf

QUERIES = [
    "이송시간 초과 광전센서",
    "P03 입구 점유",
    "BTT2-M01 기동",
    "에너지 격리 재가동",
    "매우 빨리 광전센서",
    "트레이 걸림 확인",
]


def _fill(store):
    store.replace_document("BTT-MANUAL", manual_chunks() + hybrid_extra_chunks())
    store.replace_document("BTT-SOP-001", sop_chunks())
    return store


def _results(name, tmp_path, relevant=None):
    """질의별 hybrid 상위 5개. relevant를 주면 관련 있는 청크만 남긴다."""
    with conftest.BACKENDS[name](tmp_path / name) as make:
        store = _fill(make())
        found = {
            q: [(h.chunk.chunk_id, h.score) for h in store.hybrid_query(q, k=5)]
            for q in QUERIES
        }
        if relevant is None:
            return found, _relevant(store)
        return {
            q: [x for x in hits if x[0] in relevant[q]] for q, hits in found.items()
        }


def _relevant(store):
    """키워드가 맞거나 dense cosine ≥ 0.1인 청크.

    질의와 단어가 하나도 겹치지 않는 청크는 cosine이 거의 0으로 사실상 동점이다.
    Qdrant(float32)와 파이썬(float64)의 반올림 차이로 이 꼬리 순서는 바뀔 수 있어 뺀다.
    """
    chunks = store.chunks()
    enc = conftest.SPARSE
    index = Bm25Index(
        dict(
            zip(
                [c.chunk_id for c in chunks],
                enc.encode_documents([c.text for c in chunks]),
            )
        )
    )
    return {
        q: set(index.scores(enc.encode_query(q)))
        | {h.chunk.chunk_id for h in store.query(q, k=50) if h.score >= 0.1}
        for q in QUERIES
    }


@pytest.mark.parametrize("name", ["qdrant-memory", "qdrant-path", "chroma"])
def test_backends_rank_like_reference(name, tmp_path):
    found, relevant = _results("memory", tmp_path)
    expected = {q: [x for x in found[q] if x[0] in relevant[q]] for q in QUERIES}
    actual = _results(name, tmp_path, relevant)

    for query in QUERIES:
        assert expected[query], query  # 비교할 결과가 실제로 있다
        assert [c for c, _ in actual[query]] == [c for c, _ in expected[query]], query
        assert [s for _, s in actual[query]] == pytest.approx(
            [s for _, s in expected[query]]
        )


def test_qdrant_sparse_score_equals_python_bm25():
    """DB 안의 IDF 계산(Modifier.IDF)이 Chroma 쪽 파이썬 BM25와 같은 점수를 낸다."""
    client = QdrantClient(":memory:")
    with conftest._qdrant(client) as make:
        chunks = _fill(make()).chunks()
        _check_sparse_scores(client, chunks)


def _check_sparse_scores(client, chunks):
    enc = conftest.SPARSE
    index = Bm25Index(
        {
            c.chunk_id: v
            for c, v in zip(chunks, enc.encode_documents([c.text for c in chunks]))
        }
    )

    for query in QUERIES:
        q = enc.encode_query(query)
        result = client.query_points(
            "knowledge",
            query=qm.SparseVector(indices=q.indices, values=q.values),
            using=SPARSE,
            limit=50,
            with_payload=True,
        )
        qdrant = {p.payload["chunk_id"]: p.score for p in result.points}
        python = index.scores(q)
        assert set(qdrant) == set(python), query
        for cid, score in python.items():
            assert qdrant[cid] == pytest.approx(score, rel=1e-5), (query, cid)


def test_qdrant_hybrid_score_equals_python_rrf(tmp_path):
    """DB 안의 RRF(prefetch k*4)가 파이썬 rrf()와 같은 순위·점수를 낸다."""
    with conftest.BACKENDS["qdrant-memory"](tmp_path) as make:
        store = _fill(make())
        for query in QUERIES:
            dense = [h.chunk.chunk_id for h in store.query(query, k=20)]
            q = conftest.SPARSE.encode_query(query)
            sparse = [
                p.payload["chunk_id"]
                for p in store._client.query_points(
                    "knowledge",
                    query=qm.SparseVector(indices=q.indices, values=q.values),
                    using=SPARSE,
                    limit=20,
                    with_payload=True,
                ).points
            ]
            expected = rrf([dense, sparse])[:5]
            actual = [
                (h.chunk.chunk_id, h.score) for h in store.hybrid_query(query, k=5)
            ]
            assert [c for c, _ in actual] == [c for c, _ in expected], query
            assert [s for _, s in actual] == pytest.approx([s for _, s in expected])
