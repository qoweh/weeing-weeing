"""범용 Indexer: 파일 → 파서 → 청킹 → Chunk → store.replace_document."""

import shutil
from pathlib import Path

import pytest
from fakes import FakeEmbedder, MemoryVectorStore

from weeing_weeing.rag import factory
from weeing_weeing.rag.eval_corpus import load_corpus
from weeing_weeing.rag.eval_sync import index_metadata, sync
from weeing_weeing.rag.indexer import DocumentIndexer, InvalidDocumentError
from weeing_weeing.rag.parsers import parser_for
from weeing_weeing.rag.sparse import extract_codes

DATA = Path(__file__).resolve().parents[2] / "data"
MANUAL = DATA / "manuals/BTT-MANUAL_v2.0.pdf"
SOP = DATA / "regulations/BTT-SOP-001.pdf"
META = {
    "doc_id": "BTT-MANUAL",
    "doc_version": "2.0",
    "doc_type": "manual",
    "status": "approved",
    "title": "에러코드·대응 매뉴얼",
    "source_path": "manuals/BTT-MANUAL_v2.0.pdf",
    "source_sha256": "sha-1",
}


@pytest.fixture
def memory():
    return MemoryVectorStore({}, embedder=FakeEmbedder(), embedding_model="m")


@pytest.fixture(scope="module")
def manual_chunks():
    store = MemoryVectorStore({}, embedder=FakeEmbedder(), embedding_model="m")
    count = DocumentIndexer(store).index_file(MANUAL, dict(META))
    return count, store.chunks()


def test_chunk_ids_are_continuous_and_use_given_doc_id_version(manual_chunks):
    count, chunks = manual_chunks
    assert count == len(chunks) > 10
    assert [c.chunk_id for c in chunks] == [
        f"BTT-MANUAL:2.0:{i:04d}" for i in range(count)
    ]


def test_given_metadata_is_kept_on_every_chunk(manual_chunks):
    _, chunks = manual_chunks
    for chunk in chunks:
        for key in ("doc_type", "status", "title", "source_path", "source_sha256"):
            assert chunk.metadata[key] == META[key]


def test_page_section_codes_citation_are_filled(manual_chunks):
    _, chunks = manual_chunks
    page2 = [c for c in chunks if c.metadata["page"] == 2]
    assert page2[0].metadata["section"] == "01 공통 대응·역할·우선순위"
    assert page2[0].metadata["citation"] == "BTT-MANUAL 2.0 01 공통 대응·역할·우선순위"

    with_p03 = [c for c in chunks if "P03" in c.text]
    assert with_p03 and all("BTT2-P03" in c.metadata["codes"] for c in with_p03)
    assert all(isinstance(c.metadata["page"], int) for c in chunks)
    assert all("citation" in c.metadata for c in chunks)


def test_sop_chapter_becomes_section(memory):
    meta = {**META, "doc_id": "BTT-SOP-001", "doc_version": "1.1", "doc_type": "sop"}
    DocumentIndexer(memory).index_file(SOP, meta)

    page2 = [c for c in memory.chunks() if c.metadata["page"] == 2]
    assert page2[0].metadata["section"] == "제1장 총칙"


def test_reindex_replaces_instead_of_adding(memory):
    indexer = DocumentIndexer(memory)
    first = indexer.index_file(MANUAL, dict(META))
    indexer.index_file(MANUAL, dict(META))
    assert len(memory.chunks()) == first


def test_progress_stages(memory):
    stages = []
    DocumentIndexer(memory).index_file(MANUAL, dict(META), on_progress=stages.append)
    assert stages == ["parsing", "chunking", "embedding"]


def test_previews_are_written_next_to_file_when_enabled(memory, tmp_path):
    pdf = tmp_path / "manual.pdf"
    shutil.copy(MANUAL, pdf)

    DocumentIndexer(memory, write_previews=True).index_file(pdf, dict(META))
    assert (tmp_path / "parsed.md").is_file()
    assert "## 청크 1" in (tmp_path / "chunks.md").read_text(encoding="utf-8")


def test_previews_are_off_by_default(memory, tmp_path):
    pdf = tmp_path / "manual.pdf"
    shutil.copy(MANUAL, pdf)
    DocumentIndexer(memory).index_file(pdf, dict(META))
    assert not (tmp_path / "parsed.md").exists()


@pytest.mark.parametrize(
    ("name", "content", "meta", "match"),
    [
        ("a.docx", b"x", META, "지원하지 않는"),
        ("a.pdf", b"%PDF-1.4 broken", META, "PDF 파싱"),
        ("a.pdf", b"%PDF-1.4", {"doc_version": "1"}, "doc_id"),
    ],
)
def test_invalid_input_is_reported_clearly(
    memory, tmp_path, name, content, meta, match
):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(InvalidDocumentError, match=match):
        DocumentIndexer(memory).index_file(path, dict(meta))
    assert memory.chunks() == []


def test_extract_codes_keeps_only_defined_codes():
    text = "P01/P06 확인, BTT2-M12, 센서 S01, 없는 코드 P99, 소문자 p03"
    assert extract_codes(text) == ["BTT2-P01", "BTT2-P06", "BTT2-M12", "BTT2-P03"]


def test_parser_is_chosen_by_extension():
    assert parser_for(Path("x.PDF")).name == "pdf"
    with pytest.raises(InvalidDocumentError, match="지원하지 않는"):
        parser_for(Path("x.hwp"))


def test_factory_connects_document_indexer(memory):
    assert isinstance(factory.build_indexer(memory), DocumentIndexer)


def test_sync_with_real_catalog_is_idempotent(memory):
    """make index와 같은 경로: 실제 평가 자료 목록 3종을 색인하고 다시 돌리면 전부 unchanged."""
    corpus = load_corpus(DATA / "eval/rag_documents_v1.toml")
    indexer = DocumentIndexer(memory)

    first = sync(corpus, indexer, memory)
    assert first.added == ["BTT-MANUAL", "BTT-RULE", "BTT-SOP-001"]
    assert first.ok, first.failed
    second = sync(corpus, indexer, memory)
    assert second.unchanged == ["BTT-MANUAL", "BTT-RULE", "BTT-SOP-001"]

    for entry in corpus.documents:  # 변경 감지에 쓰는 값이 모든 청크에 그대로 있다
        expected = index_metadata(entry, "x")
        for chunk in memory.chunks(where={"doc_id": entry.doc_id}):
            assert chunk.metadata["status"] == expected["status"]
            assert chunk.metadata["source_path"] == expected["source_path"]


def test_manual_deletion_does_not_delete_report_vectors(memory):
    from weeing_weeing.rag.store import Chunk

    memory.replace_document(
        "REPORT",
        [
            Chunk(
                chunk_id="REPORT:1:0001",
                doc_id="REPORT",
                doc_version="1",
                text="확정 정비 이력",
                metadata={"doc_type": "report", "status": "approved"},
            )
        ],
    )
    with pytest.raises(InvalidDocumentError, match="보고서"):
        DocumentIndexer(memory).delete_document("REPORT")
    with pytest.raises(InvalidDocumentError, match="보고서"):
        DocumentIndexer(memory).index_file(MANUAL, {**META, "doc_id": "REPORT"})
    assert memory.chunks(where={"doc_id": "REPORT"})
