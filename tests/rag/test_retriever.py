"""공개 검색 계약과 저장소의 하이브리드 검색 연결을 검증한다."""

from unittest.mock import Mock

import pytest

from weeing_weeing.contracts import Evidence
from weeing_weeing.rag.interface import HybridRetriever, Retriever
from weeing_weeing.rag.store import Chunk, Hit, VectorStore


def chunk(seq=0, **metadata):
    return Chunk(
        f"BTT-MANUAL:2.0:{seq:04d}",
        "BTT-MANUAL",
        "2.0",
        "이송 시간 초과 광전 센서 점검",
        metadata,
    )


def test_search_preserves_rank_scores_and_citations():
    store = Mock(spec=VectorStore)
    store.hybrid_query.return_value = [
        Hit(chunk(1, section="03 현장 대응", citation="매뉴얼 2.0 3절 P01"), 0.03),
        Hit(chunk(0), 0.02),
    ]
    retriever: Retriever = HybridRetriever(store)

    found = retriever.search("이송 시간 초과", k=2)

    store.hybrid_query.assert_called_once_with("이송 시간 초과", k=2, where=None)
    assert found == [
        Evidence(
            evidence_id="BTT-MANUAL:2.0:0001",
            doc_id="BTT-MANUAL",
            doc_version="2.0",
            section="03 현장 대응",
            text="이송 시간 초과 광전 센서 점검",
            score=0.03,
            citation="매뉴얼 2.0 3절 P01",
        ),
        Evidence(
            evidence_id="BTT-MANUAL:2.0:0000",
            doc_id="BTT-MANUAL",
            doc_version="2.0",
            text="이송 시간 초과 광전 센서 점검",
            score=0.02,
            citation="BTT-MANUAL 2.0",
        ),
    ]


def test_missing_citation_uses_only_stored_source_metadata():
    store = Mock(spec=VectorStore)
    store.hybrid_query.return_value = [Hit(chunk(section="03 현장 대응", page=4), 0.03)]

    found = HybridRetriever(store).search("센서")

    assert found[0].citation == "BTT-MANUAL 2.0 03 현장 대응 p.4"
    assert found[0].page == 4


def test_pdf_location_is_read_from_metadata_without_guessing_chunk_number():
    store = Mock(spec=VectorStore)
    store.hybrid_query.return_value = [
        Hit(chunk(10, title="설비 매뉴얼", page=8, section="고온 점검"), 0.03)
    ]
    [evidence] = HybridRetriever(store).search("고온")
    assert evidence.page == 8 and evidence.title == "설비 매뉴얼"
    store.hybrid_query.return_value = [Hit(chunk(10, section="고온 점검"), 0.03)]
    assert HybridRetriever(store).search("고온")[0].page is None


def test_code_alias_is_forwarded_without_mutating_filters():
    store = Mock(spec=VectorStore)
    store.hybrid_query.return_value = []
    filters = {"code": "BTT2-P01", "doc_type": "manual", "status": "approved"}

    assert HybridRetriever(store).search("센서", filters=filters) == []

    store.hybrid_query.assert_called_once_with(
        "센서",
        k=5,
        where={"codes": "BTT2-P01", "doc_type": "manual", "status": "approved"},
    )
    assert filters["code"] == "BTT2-P01"
    assert "codes" not in filters


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
        {"query": " \n\t"},
        {"k": 0},
        {"k": -1},
        {"k": 1.5},
        {"k": True},
        {"filters": {"codes": []}},
        {"filters": {"code": "BTT2-P01", "codes": ["BTT2-P03"]}},
        {"filters": {"doc_type": {"$eq": "manual"}}},
        {"filters": {"status": None}},
        {"filters": {"codes": [1]}},
    ],
)
def test_invalid_input_is_rejected_before_search(kwargs):
    store = Mock(spec=VectorStore)

    with pytest.raises((TypeError, ValueError)):
        HybridRetriever(store).search(**{"query": "센서", **kwargs})

    store.hybrid_query.assert_not_called()


def test_store_failure_is_not_reported_as_no_evidence():
    store = Mock(spec=VectorStore)
    store.hybrid_query.side_effect = TimeoutError("검색 시간 초과")

    with pytest.raises(TimeoutError, match="검색 시간 초과"):
        HybridRetriever(store).search("센서")


def test_search_with_each_store_backend(store):
    retriever = HybridRetriever(store)
    assert retriever.search("센서") == []
    store.replace_document(
        "BTT-MANUAL",
        [
            chunk(0, codes=["BTT2-P01"], doc_type="manual", status="approved"),
            chunk(1, codes=["BTT2-P03"], doc_type="manual", status="draft"),
        ],
    )

    found = retriever.search("센서", filters={"code": "BTT2-P01"}, k=1)

    assert [item.evidence_id for item in found] == ["BTT-MANUAL:2.0:0000"]
    assert found[0].score > 0
    assert retriever.search("센서", filters={"codes": ["BTT2-M01"]}) == []
    assert (
        len(retriever.search("센서", filters={"codes": ["BTT2-P01", "BTT2-P03"]})) == 2
    )
    assert len(retriever.search("센서", filters={"status": "approved"})) == 1


def test_reranking_expands_candidates_before_selecting_k():
    store = Mock(spec=VectorStore)
    candidates = [
        Hit(chunk(i, citation=f"매뉴얼 {i}"), 0.03 - i * 0.01) for i in range(3)
    ]
    store.hybrid_query.return_value = candidates
    reranker = Mock()
    reranker.rerank.return_value = list(reversed(candidates))
    filters = {"code": "BTT2-P01", "status": "approved"}

    found = HybridRetriever(store, reranker=reranker, candidate_k=30).search(
        "센서", k=1, filters=filters
    )

    store.hybrid_query.assert_called_once_with(
        "센서", k=30, where={"codes": "BTT2-P01", "status": "approved"}
    )
    reranker.rerank.assert_called_once_with("센서", candidates)
    assert [e.evidence_id for e in found] == [candidates[2].chunk.chunk_id]
    assert found[0].score == candidates[2].score
    assert found[0].citation == "매뉴얼 2"
    assert filters == {"code": "BTT2-P01", "status": "approved"}


def test_candidate_count_is_at_least_final_k():
    store = Mock(spec=VectorStore)
    store.hybrid_query.return_value = []
    reranker = Mock()
    assert (
        HybridRetriever(store, reranker=reranker, candidate_k=2).search("센서", k=5)
        == []
    )
    store.hybrid_query.assert_called_once_with("센서", k=5, where=None)
    reranker.rerank.assert_not_called()


def test_reranking_failure_is_propagated():
    store = Mock(spec=VectorStore)
    store.hybrid_query.return_value = [Hit(chunk(), 0.03)]
    reranker = Mock()
    reranker.rerank.side_effect = RuntimeError("리랭킹 실패")
    with pytest.raises(RuntimeError, match="리랭킹 실패"):
        HybridRetriever(store, reranker=reranker).search("센서")


@pytest.mark.parametrize("candidate_k", [0, -1, True, 1.5])
def test_invalid_candidate_count(candidate_k):
    with pytest.raises((ValueError, TypeError)):
        HybridRetriever(Mock(spec=VectorStore), candidate_k=candidate_k)


def test_reranking_with_each_store_backend(store):
    store.replace_document(
        "BTT-MANUAL",
        [chunk(i, codes=["BTT2-P01"], status="approved") for i in range(3)],
    )
    candidates = store.hybrid_query("센서", k=3, where={"codes": "BTT2-P01"})
    reranker = Mock()
    reranker.rerank.side_effect = lambda query, hits: list(reversed(hits))
    found = HybridRetriever(store, reranker=reranker, candidate_k=3).search(
        "센서", k=1, filters={"code": "BTT2-P01"}
    )
    assert [e.evidence_id for e in found] == [candidates[-1].chunk.chunk_id]


@pytest.mark.parametrize(
    "minimum, expected", [(None, [0, 1, 2]), (0.5, [0, 1]), (1, [])]
)
def test_relevance_reaches_evidence_and_filter_runs_before_final_k(minimum, expected):
    store = Mock(spec=VectorStore)
    # 후순위의 관련 근거도 k를 고르기 전에 검사한다. RRF 크기는 판단에 쓰지 않는다.
    candidates = [Hit(chunk(i), score) for i, score in enumerate([0.01, 0.02, 0.03])]
    store.hybrid_query.return_value = candidates
    reranker = Mock()
    reranker.rerank.return_value = [
        Hit(candidates[i].chunk, candidates[i].score, relevance)
        for i, relevance in enumerate([0.9, 0.5, 0.1])
    ]
    found = HybridRetriever(store, reranker=reranker, min_relevance=minimum).search(
        "센서", k=2
    )
    assert [e.evidence_id for e in found] == [
        candidates[i].chunk.chunk_id for i in expected[:2]
    ]
    assert [e.score for e in found] == [candidates[i].score for i in expected[:2]]
    assert [e.relevance for e in found] == [[0.9, 0.5, 0.1][i] for i in expected[:2]]


def test_unranked_results_have_unknown_relevance():
    store = Mock(spec=VectorStore)
    store.hybrid_query.return_value = [Hit(chunk(), 0.03)]
    assert HybridRetriever(store).search("센서")[0].relevance is None


@pytest.mark.parametrize(
    "minimum", [True, "0.5", float("nan"), float("inf"), -float("inf")]
)
def test_invalid_relevance_threshold_is_rejected(minimum):
    with pytest.raises((ValueError, TypeError)):
        HybridRetriever(Mock(spec=VectorStore), reranker=Mock(), min_relevance=minimum)


def test_relevance_filter_requires_reranker_even_with_zero_threshold():
    with pytest.raises(ValueError, match="리랭커가 필요"):
        HybridRetriever(Mock(spec=VectorStore), min_relevance=0)


@pytest.mark.parametrize("relevance", [None, float("nan"), float("inf")])
def test_filter_rejects_missing_or_invalid_model_score(relevance):
    store = Mock(spec=VectorStore)
    store.hybrid_query.return_value = [Hit(chunk(), 0.03)]
    reranker = Mock()
    reranker.rerank.return_value = [Hit(chunk(), 0.03, relevance)]
    with pytest.raises(ValueError, match="리랭커 점수"):
        HybridRetriever(store, reranker=reranker, min_relevance=0.5).search("센서")


def test_relevance_filter_with_model_and_each_store_backend(store, monkeypatch):
    from weeing_weeing.rag import reranker
    from weeing_weeing.rag.reranker import VoyageReranker

    store.replace_document(
        "BTT-MANUAL", [chunk(i, citation=f"인용 {i}") for i in range(3)]
    )
    candidates = store.hybrid_query("센서", k=30)
    scores = [0.01, 0.9, 0.5]

    def post(path, payload, **kwargs):
        return {
            "data": [
                {"index": i, "relevance_score": scores[i]}
                for i in range(len(payload["documents"]))
            ]
        }

    monkeypatch.setattr(reranker, "voyage_post", post)
    retriever = HybridRetriever(
        store, reranker=VoyageReranker("rerank-3-lite"), min_relevance=0.5
    )
    found = retriever.search("센서", k=1)
    assert len(found) == 1
    assert found[0].evidence_id == candidates[1].chunk.chunk_id
    assert found[0].relevance == 0.9
    assert found[0].score == candidates[1].score
    assert found[0].citation == candidates[1].chunk.metadata["citation"]
    scores[:] = [0.01, 0.02, 0.03]
    assert retriever.search("용접 로봇", k=2) == []
    assert retriever.search("센서", filters={"doc_id": "없는 문서"}) == []
