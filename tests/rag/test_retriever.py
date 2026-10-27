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
