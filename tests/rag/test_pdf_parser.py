from pathlib import Path
from types import SimpleNamespace

import pytest

from weeing_weeing.rag.pdf_parser import (
    ParserConfig,
    parse_pdf,
    save_markdown,
    table_to_markdown,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MANUAL = DATA_DIR / "knowledge/btt-manual_v2.0_error_response.pdf"


@pytest.mark.parametrize(
    ("relative_path", "doc_type"),
    [
        ("knowledge/btt-manual_v2.0_error_response.pdf", "manual"),
        ("knowledge/btt-rule_v2.0_rulebook.pdf", "rulebook"),
        ("knowledge/btt-sop-001_draft.pdf", "regulation"),
        ("templates/maintenance_report_form_v1.2.pdf", "report_template"),
    ],
)
def test_document_types_keep_source_metadata(relative_path, doc_type):
    source = DATA_DIR / relative_path
    documents = parse_pdf(
        source, doc_id="TEST-DOC", doc_version="test", doc_type=doc_type
    )

    assert documents
    for page, document in enumerate(documents, start=1):
        assert document.metadata == {
            "doc_id": "TEST-DOC",
            "doc_version": "test",
            "doc_type": doc_type,
            "source": source.name,
            "page": page,
        }
        assert document.page_content.removeprefix(f"## 페이지 {page}").strip()


def test_manual_headers_and_body_order_without_duplicate_table_text():
    documents = parse_pdf(
        MANUAL,
        doc_id="BTT-MANUAL",
        doc_version="v2.0",
        doc_type="manual",
        asset_id="TEST-ASSET",
        config=ParserConfig(margin_top=45, margin_bottom=50, infer_table_columns=True),
    )

    page_two = documents[1].page_content
    assert "| 상태 | 운영 대응 |" in page_two
    assert "| Normal | 측정값과 필수 문맥" in page_two
    assert page_two.count("측정값과 필수 문맥") == 1
    assert page_two.index("01 공통") < page_two.index("| 상태 |")
    assert page_two.index("| 상태 |") < page_two.index("공통 대응 순서")
    assert "BATTERY TRAY TRANSFER" not in page_two
    assert "| 코드 | 표시명 / 트리거 | 우선 확인 / 회복 |" in (
        documents[2].page_content
    )
    assert documents[1].metadata["asset_id"] == "TEST-ASSET"


def test_form_without_header_keeps_first_and_single_rows():
    markdown = table_to_markdown(
        [["설비명", "BLDC-001"], ["실제 수행 조치", None]], has_header=False
    )
    assert "| 설비명 | BLDC-001 |" in markdown
    assert "| 실제 수행 조치 |  |" in markdown
    assert "| 입력 항목 | 입력값 |" in table_to_markdown([["입력 항목", "입력값"]])


def test_save_markdown_keeps_page_boundaries(tmp_path):
    documents = parse_pdf(
        MANUAL, doc_id="BTT-MANUAL", doc_version="v2.0", doc_type="manual"
    )
    output = save_markdown(documents, tmp_path / "parsed/manual.md")

    assert output.read_text(encoding="utf-8") == "\n\n---\n\n".join(
        document.page_content for document in documents
    )


def test_scanned_or_empty_page_is_not_silently_indexed(monkeypatch):
    class EmptyPDF:
        pages = [
            SimpleNamespace(
                height=100,
                bbox=(0, 0, 100, 100),
                crop=lambda bbox: SimpleNamespace(chars=[]),
            )
        ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "weeing_weeing.rag.pdf_parser.pdfplumber.open", lambda path: EmptyPDF()
    )
    with pytest.raises(ValueError, match="1페이지.*텍스트가 없습니다"):
        parse_pdf("scan.pdf", doc_id="scan", doc_version="v1", doc_type="manual")


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_invalid_margins_are_rejected(value):
    with pytest.raises(ValueError, match="margin_top"):
        ParserConfig(margin_top=value)
