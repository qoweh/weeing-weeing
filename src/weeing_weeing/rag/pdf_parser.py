"""PDF를 페이지별 Markdown Document로 추출한다. 청킹·임베딩은 담당하지 않는다."""

import argparse
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber
from langchain_core.documents import Document
from pdfplumber.page import Page
from pdfplumber.table import Table


@dataclass(frozen=True)
class ParserConfig:
    """PDF 레이아웃별 설정. 좌표·간격의 단위는 PDF 포인트(1/72인치)다."""

    # 다른 양식의 본문이 잘리지 않도록 기본값은 여백을 제거하지 않는다.
    margin_top: float = 0
    margin_bottom: float = 0
    infer_table_columns: bool = False
    header_gap: float = 12
    table_has_header: bool = True
    single_row_as_quote: bool = False
    table_settings: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("margin_top", "margin_bottom", "header_gap"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name}은 유한한 0 이상의 값이어야 합니다.")


def clean_cell(value: str | None) -> str:
    """셀의 시각적 줄바꿈은 공백으로 합치고 Markdown 문자를 이스케이프한다."""
    text = " ".join((value or "").split())
    return text.replace("\\", "\\\\").replace("|", r"\|")


def table_to_markdown(
    rows: list[list[str | None]],
    *,
    has_header: bool = True,
    single_row_as_quote: bool = False,
) -> str:
    """표를 변환한다. 헤더가 없는 양식에는 임시 열 이름을 붙여 첫 행을 보존한다."""
    if not rows or not any(any(cell for cell in row) for row in rows):
        return ""

    width = max(len(row) for row in rows)
    normalized = [
        [clean_cell(cell) for cell in row] + [""] * (width - len(row)) for row in rows
    ]

    # 한 행에 내용 셀이 하나뿐이면 안내 박스로 처리한다.
    if single_row_as_quote and len(normalized) == 1:
        contents = [cell for cell in normalized[0] if cell.strip()]
        if len(contents) == 1:
            return f"> {contents[0]}"

    if has_header and len(normalized) > 1:
        header, body = normalized[0], normalized[1:]
    else:
        header = [f"열 {index + 1}" for index in range(width)]
        body = normalized

    def render_row(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    return "\n".join(
        [render_row(header), render_row(["---"] * width)]
        + [render_row(row) for row in body]
    )


def extract_table_rows(
    page: Page, table: Table, config: ParserConfig
) -> list[list[str | None]]:
    """기본 추출을 우선하고, 요청한 경우에만 헤더 간격으로 열을 보완한다."""
    rows = table.extract()
    if (
        not config.infer_table_columns
        or not config.table_has_header
        or len(rows) < 2
        or len(rows[0]) > 1
    ):
        return rows

    words = page.crop(table.rows[0].bbox).extract_words()
    if not words:
        return rows

    first_top = min(word["top"] for word in words)
    first_line = sorted(
        [word for word in words if abs(word["top"] - first_top) < 3],
        key=lambda word: word["x0"],
    )
    groups: list[dict[str, float]] = []
    for word in first_line:
        # 「운영 대응」 같은 제목을 띄어쓰기마다 새 열로 나누지 않는다.
        if groups and word["x0"] - groups[-1]["x1"] <= config.header_gap:
            groups[-1]["x1"] = max(groups[-1]["x1"], word["x1"])
        else:
            groups.append({"x0": word["x0"], "x1": word["x1"]})

    if len(groups) < 2:
        return rows

    left, _, right, bottom = table.bbox
    column_edges = [left, *(group["x0"] - 3 for group in groups[1:]), right]
    if any(a >= b for a, b in zip(column_edges, column_edges[1:])):
        return rows

    extracted = page.crop(table.bbox).extract_table(
        {
            "vertical_strategy": "explicit",
            "explicit_vertical_lines": column_edges,
            "horizontal_strategy": "explicit",
            "explicit_horizontal_lines": sorted(
                {row.bbox[1] for row in table.rows} | {bottom}
            ),
        }
    )
    return extracted or rows


def extract_page_markdown(page: Page, config: ParserConfig) -> str:
    """표 영역을 본문에서 제외하고, 좌표 순서로 본문과 표를 합친다."""
    tables = page.find_tables(table_settings=config.table_settings)

    def outside_tables(obj: dict[str, Any]) -> bool:
        if obj.get("object_type") != "char":
            return True
        center_x = (obj["x0"] + obj["x1"]) / 2
        center_y = (obj["top"] + obj["bottom"]) / 2
        return not any(
            left <= center_x <= right and top <= center_y <= bottom
            for left, top, right, bottom in (table.bbox for table in tables)
        )

    # 높이 구간 전체를 잘라내지 않아 표 옆에 있는 본문도 보존한다.
    body = page.filter(outside_tables)
    blocks = [
        (line["top"], line["x0"], line["text"]) for line in body.extract_text_lines()
    ]
    for table in tables:
        rows = extract_table_rows(page, table, config)
        markdown = table_to_markdown(
            rows,
            has_header=config.table_has_header,
            single_row_as_quote=config.single_row_as_quote,
        )
        if markdown:
            blocks.append((table.bbox[1], table.bbox[0], markdown))

    # 단일 단 흐름 기준이다. 복잡한 다단 문서는 읽기 순서를 별도 검증해야 한다.
    blocks.sort(key=lambda block: (block[0], block[1]))
    return "\n".join(
        f"\n{text}\n" if text.startswith(("| ", "> ")) else text
        for _, _, text in blocks
        if text.strip()
    ).strip()


def parse_pdf(
    pdf_path: str | Path,
    *,
    doc_id: str,
    doc_version: str,
    doc_type: str,
    asset_id: str | None = None,
    config: ParserConfig | None = None,
) -> list[Document]:
    """매뉴얼·규정·보고서 등의 PDF에서 페이지별 텍스트와 출처를 반환한다.

    doc_type은 분류용 메타데이터이며 레이아웃을 자동 판별하지 않는다.
    OCR은 수행하지 않는다. 텍스트 없는 페이지는 조용히 누락하지 않고 알린다.
    """
    if not all(value.strip() for value in (doc_id, doc_version, doc_type)):
        raise ValueError("doc_id, doc_version, doc_type은 비워 둘 수 없습니다.")

    pdf_path = Path(pdf_path)
    config = config or ParserConfig()
    documents = []
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            raise ValueError("PDF에 페이지가 없습니다.")
        for page_number, original in enumerate(pdf.pages, start=1):
            if config.margin_top + config.margin_bottom >= original.height:
                raise ValueError(f"{page_number}페이지보다 제외 여백이 큽니다.")
            left, top, right, bottom = original.bbox
            page = original.crop(
                (left, top + config.margin_top, right, bottom - config.margin_bottom)
            )
            if not page.chars:
                raise ValueError(
                    f"{pdf_path.name} {page_number}페이지에 텍스트가 없습니다. "
                    "빈 페이지인지, OCR이 필요한 스캔인지 확인하세요."
                )
            content = extract_page_markdown(page, config)
            if not content.strip():
                raise ValueError(f"{page_number}페이지에서 본문을 추출하지 못했습니다.")

            metadata = {
                "doc_id": doc_id,
                "doc_version": doc_version,
                "doc_type": doc_type,
                "source": pdf_path.name,
                "page": page_number,
            }
            if asset_id is not None:
                metadata["asset_id"] = asset_id
            documents.append(
                Document(
                    page_content=f"## 페이지 {page_number}\n\n{content}",
                    metadata=metadata,
                )
            )
    return documents


def save_markdown(documents: list[Document], output_path: str | Path) -> Path:
    """육안 검토용으로 저장한다. RAG에는 메타데이터가 있는 Document를 전달한다."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = "\n\n---\n\n".join(document.page_content for document in documents)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def main() -> None:
    """입력 문서와 설정을 받아 검토용 Markdown 파일을 만든다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--doc-version", required=True)
    parser.add_argument("--doc-type", required=True)
    parser.add_argument("--asset-id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--margin-top", type=float, default=0)
    parser.add_argument("--margin-bottom", type=float, default=0)
    parser.add_argument("--infer-table-columns", action="store_true")
    parser.add_argument("--table-without-header", action="store_true")
    parser.add_argument("--single-row-as-quote", action="store_true")
    args = parser.parse_args()
    if args.pdf_path.resolve() == args.output.resolve():
        parser.error("원본 PDF와 출력 파일의 경로는 달라야 합니다.")
    documents = parse_pdf(
        args.pdf_path,
        doc_id=args.doc_id,
        doc_version=args.doc_version,
        doc_type=args.doc_type,
        asset_id=args.asset_id,
        config=ParserConfig(
            margin_top=args.margin_top,
            margin_bottom=args.margin_bottom,
            infer_table_columns=args.infer_table_columns,
            table_has_header=not args.table_without_header,
            single_row_as_quote=args.single_row_as_quote,
        ),
    )
    output = save_markdown(documents, args.output)
    print(f"{len(documents)}페이지 파싱 완료: {output}")


if __name__ == "__main__":
    main()
