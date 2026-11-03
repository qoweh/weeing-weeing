"""형식별 파서 등록. 파일 하나를 페이지별 Document(본문 + page 메타데이터)로 바꾼다.

    parser_for(path) → 확장자에 맞는 파서 → parse(path, doc_id=…, doc_version=…, doc_type=…)

새 형식(DOCX, XLSX, Markdown, 정비 이력 JSONL 등)은 Parser 모양의 클래스를 만들어
register_parser()로 등록하면 Indexer가 그대로 쓴다. 지금은 PDF만 있다.
"""

from pathlib import Path
from typing import Protocol

from langchain_core.documents import Document

from weeing_weeing.rag.interface import InvalidDocumentError
from weeing_weeing.rag.pdf_parser import ParserConfig, parse_pdf


class UnsupportedFormatError(InvalidDocumentError):
    """등록된 파서가 없는 파일 형식."""


class Parser(Protocol):
    name: str
    suffixes: tuple[str, ...]  # 소문자 확장자. 예: (".pdf",)

    def parse(
        self, path: Path, *, doc_id: str, doc_version: str, doc_type: str
    ) -> list[Document]:
        """페이지(또는 그에 해당하는 단위)별 Document. metadata에 page를 넣는다."""
        ...


# BTT 문서 양식(매뉴얼·룰 정의서·SOP 공통): 머리글·바닥글 여백을 빼고 표 열을 추론한다.
# 머리글("BATTERY TRAY TRANSFER …")이 페이지마다 반복되지 않고 각 페이지가 절 제목으로 시작한다.
BTT_PDF = ParserConfig(
    margin_top=45, margin_bottom=50, infer_table_columns=True, single_row_as_quote=True
)


class PdfParser:
    name = "pdf"
    suffixes = (".pdf",)

    def __init__(self, config: ParserConfig = BTT_PDF) -> None:
        self.config = config

    def parse(
        self, path: Path, *, doc_id: str, doc_version: str, doc_type: str
    ) -> list[Document]:
        return parse_pdf(
            path,
            doc_id=doc_id,
            doc_version=doc_version,
            doc_type=doc_type,
            config=self.config,
        )


_PARSERS: list[Parser] = [PdfParser()]


def register_parser(parser: Parser) -> None:
    """나중에 등록한 파서가 같은 확장자에서 우선한다."""
    _PARSERS.insert(0, parser)


def parser_for(path: Path) -> Parser:
    suffix = path.suffix.lower()
    for parser in _PARSERS:
        if suffix in parser.suffixes:
            return parser
    supported = sorted({s for p in _PARSERS for s in p.suffixes})
    raise UnsupportedFormatError(
        f"지원하지 않는 형식이다: {suffix or '(확장자 없음)'}. 지원: {', '.join(supported)}"
    )
