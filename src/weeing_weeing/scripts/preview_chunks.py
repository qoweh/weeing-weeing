from pathlib import Path

from weeing_weeing.rag.chunker import ChunkerConfig, chunk_documents
from weeing_weeing.rag.pdf_parser import ParserConfig, parse_pdf


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    pdf_path = project_root / "data/manuals/BTT-MANUAL_v2.0.pdf"

    # 1. PDF를 페이지별 Document로 변환
    documents = parse_pdf(
        pdf_path,
        doc_id="BTT-MANUAL",
        doc_version="v2.0",
        doc_type="manual",
        config=ParserConfig(
            margin_top=45,
            margin_bottom=50,
            infer_table_columns=True,
            single_row_as_quote=True,
        ),
    )

    # 2. 페이지별 Document를 청크로 분할
    chunks = chunk_documents(
        documents,
        config=ChunkerConfig(chunk_size=1000, chunk_overlap=150),
    )

    output_path = project_root / "data/chunked/manual_chunks_preview.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sections = []
    for number, chunk in enumerate(chunks, start=1):
        sections.append(
            f"## 청크 {number}\n\n"
            f"- 문자 수: {len(chunk.page_content)}\n"
            f"- 메타데이터: {chunk.metadata}\n\n"
            f"{chunk.page_content}"
        )

    output_path.write_text(
        "\n\n---\n\n".join(sections),
        encoding="utf-8",
    )
    print(f"청킹 결과 저장: {output_path}")


if __name__ == "__main__":
    main()
