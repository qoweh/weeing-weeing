"""PDF를 두 방식으로 청킹해 비교용 Markdown만 생성한다 (DB 사용 안 함)."""

import argparse
import json
from pathlib import Path

from weeing_weeing.rag.chunker import chunk_documents
from weeing_weeing.rag.indexer import DocumentIndexer, page_section
from weeing_weeing.rag.parsers import parser_for
from weeing_weeing.rag.structured_chunker import structured_chunk_documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--version", default="1.0")
    parser.add_argument("--doc-type", default="manual")
    parser.add_argument("--asset-id", default="")
    args = parser.parse_args()

    pages = parser_for(args.pdf).parse(
        args.pdf, doc_id=args.doc_id, doc_version=args.version, doc_type=args.doc_type
    )
    section = None
    for page in pages:
        section = page_section(page.page_content) or section
        if section:
            page.metadata["section"] = section
    metadata = {
        "doc_id": args.doc_id,
        "doc_version": args.version,
        "doc_type": args.doc_type,
        "asset_id": args.asset_id,
        "title": args.pdf.name,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, pieces in (
        ("기존", chunk_documents(pages)),
        ("구조기반", structured_chunk_documents(pages)),
    ):
        output = [f"# {args.pdf.name} — {name} 청킹\n\n총 {len(pieces)}개 청크"]
        for index, piece in enumerate(pieces):
            chunk = DocumentIndexer._chunk(index, piece, metadata)
            values = dict(chunk.metadata)
            output.append(
                f"## 청크 {index + 1}\n\n- ID: {chunk.chunk_id}\n"
                f"- 문자 수: {len(chunk.text)}\n"
                f"- 메타데이터: {json.dumps(values, ensure_ascii=False)}\n\n{chunk.text}"
            )
        destination = args.output_dir / f"{args.doc_id}-{name}.md"
        destination.write_text("\n\n---\n\n".join(output) + "\n", encoding="utf-8")
        print(f"{destination}: {len(pieces)}개")


if __name__ == "__main__":
    main()
