"""승인 정비 이력은 사람 작성 내용만 한 청크로 검색할 수 있어야 한다."""

import json
from pathlib import Path

import pytest
from fakes import FakeEmbedder, MemoryVectorStore

from weeing_weeing.contracts import MaintenanceReport
from weeing_weeing.rag.indexer import DocumentIndexer
from weeing_weeing.rag.report import report_chunk
from weeing_weeing.rag.retriever import HybridRetriever
from weeing_weeing.rag.sparse import KiwiBm25Encoder

DATA = Path(__file__).resolve().parents[2] / "data/history/synthetic_reports_v1.jsonl"


def reports():
    return [
        MaintenanceReport.model_validate(json.loads(line))
        for line in DATA.read_text(encoding="utf-8").splitlines()
    ]


def memory():
    return MemoryVectorStore(
        {},
        embedder=FakeEmbedder(),
        embedding_model="test",
        sparse_encoder=KiwiBm25Encoder(),
    )


def test_only_human_fields_are_in_text_or_metadata():
    report = reports()[0].model_copy(deep=True)
    report.ai_analysis.observed_facts = "AI_ONLY_SENTINEL"
    report.ai_analysis.suspected_causes[0].cause = "AI_GUESS_SENTINEL"
    report.approval[0].comment = "APPROVAL_SENTINEL"
    report.maintenance.remarks = "REMARKS_SENTINEL"
    report.incident.reason = "INCIDENT_SENTINEL"
    chunk = report_chunk(report)

    assert chunk.chunk_id == f"{report.report_id}:1:0001"
    assert chunk.doc_id == report.report_id
    assert chunk.metadata["doc_type"] == "report"
    assert chunk.metadata["status"] == "approved"
    assert chunk.metadata["codes"] == report.incident.codes
    assert chunk.metadata["data_origin"] == "SYNTHETIC"
    assert "가상 사례" in chunk.metadata["citation"]
    assert report.maintenance.confirmed_cause in chunk.text
    assert report.maintenance.actions_taken[0].action in chunk.text
    combined = chunk.text + str(chunk.metadata)
    for forbidden in (
        "AI_ONLY_SENTINEL",
        "AI_GUESS_SENTINEL",
        "APPROVAL_SENTINEL",
        "REMARKS_SENTINEL",
        "INCIDENT_SENTINEL",
    ):
        assert forbidden not in combined


@pytest.mark.parametrize("status", ["DRAFT", "SUBMITTED", "REVIEWED", "REJECTED"])
def test_only_approved_report_can_be_indexed(status):
    report = reports()[0].model_copy(deep=True)
    report.report_status = status
    with pytest.raises(ValueError, match="최종 승인"):
        DocumentIndexer(memory()).index_report(report)


def test_revision_replaces_previous_chunk_and_search_cites_report():
    report = reports()[0]
    store = memory()
    indexer = DocumentIndexer(store)
    assert indexer.index_report(report) == 1
    revised = report.model_copy(deep=True)
    revised.report_version = 2
    revised.maintenance.confirmed_cause = "개정판에서 확인한 가이드 간섭"
    assert indexer.index_report(revised) == 1
    assert [chunk.chunk_id for chunk in store.chunks()] == [
        f"{report.report_id}:2:0001"
    ]
    found = HybridRetriever(store).search(
        "개정판에서 확인한 가이드 간섭",
        filters={"doc_type": "report", "status": "approved"},
    )
    assert len(found) == 1
    assert found[0].doc_id == report.report_id
    assert report.report_id in found[0].citation
    assert "가상 사례" in found[0].citation
    assert "개정판에서 확인한 가이드 간섭" in found[0].text


def test_all_24_synthetic_cases_are_searchable_by_code():
    store = memory()
    indexer = DocumentIndexer(store)
    for report in reports():
        assert indexer.index_report(report) == 1
    assert len(store.chunks()) == 24
    found = HybridRetriever(store).search(
        "입구 센서 장기 점유 원인",
        k=5,
        filters={"doc_type": "report", "code": "BTT2-P03"},
    )
    assert len(found) == 3
    assert all("가상 사례" in item.citation for item in found)
    assert all(item.doc_id.startswith("RPT-SYN-") for item in found)


@pytest.mark.parametrize("backend", ["qdrant", "chroma"])
def test_report_search_works_in_vector_backends(backend, tmp_path):
    report = reports()[0]
    embedder = FakeEmbedder()
    sparse = KiwiBm25Encoder()
    if backend == "qdrant":
        from qdrant_client import QdrantClient

        from weeing_weeing.rag.qdrant_store import QdrantVectorStore

        client = QdrantClient(":memory:")
        store = QdrantVectorStore(
            client,
            embedder=embedder,
            sparse_encoder=sparse,
            embedding_model="test",
        )
    else:
        import chromadb
        from chromadb.config import Settings

        from weeing_weeing.rag.chroma_store import ChromaVectorStore

        client = chromadb.PersistentClient(
            path=str(tmp_path / "chroma"),
            settings=Settings(anonymized_telemetry=False),
        )
        store = ChromaVectorStore(
            client,
            embedder=embedder,
            sparse_encoder=sparse,
            embedding_model="test",
        )
    try:
        indexer = DocumentIndexer(store)
        assert indexer.index_report(report) == 1
        found = HybridRetriever(store).search(
            report.maintenance.confirmed_cause,
            filters={"doc_type": "report", "code": report.incident.codes[0]},
        )
        assert len(found) == 1
        assert found[0].doc_id == report.report_id
        assert "가상 사례" in found[0].citation
    finally:
        if backend == "qdrant":
            client.close()
