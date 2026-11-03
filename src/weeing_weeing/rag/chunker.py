"""페이지별 Document를 본문·표 청크로 나누고 출처 메타데이터를 유지한다."""

import re
from copy import deepcopy
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# pdf_parser가 만드는 Markdown 표의 구분선: | --- | --- |
_TABLE_SEPARATOR = re.compile(r"\|(?:\s*:?-{3,}:?\s*\|)+")


@dataclass(frozen=True)
class ChunkerConfig:
    """크기는 토큰 수가 아닌 문자 수 기준이다."""

    chunk_size: int = 1000
    chunk_overlap: int = 150

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size는 0보다 커야 합니다.")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("chunk_overlap은 0 이상, chunk_size 미만이어야 합니다.")


def _is_table_row(line: str) -> bool:
    """파서가 생성한 파이프 형식의 표 행인지 확인한다."""
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """본문과 Markdown 표를 원래 순서대로 구분한다."""
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    body: list[str] = []
    index = 0

    while index < len(lines):
        starts_table = (
            index + 1 < len(lines)
            and _is_table_row(lines[index])
            and _TABLE_SEPARATOR.fullmatch(lines[index + 1].strip()) is not None
        )

        if not starts_table:
            body.append(lines[index])
            index += 1
            continue

        body_text = "\n".join(body).strip()
        if body_text:
            blocks.append(("text", body_text))
        body = []

        table = [lines[index].strip(), lines[index + 1].strip()]
        index += 2

        while index < len(lines) and _is_table_row(lines[index]):
            table.append(lines[index].strip())
            index += 1

        blocks.append(("table", "\n".join(table)))

    body_text = "\n".join(body).strip()
    if body_text:
        blocks.append(("text", body_text))

    return blocks


@dataclass(frozen=True)
class _ChunkUnit:
    """청크에 넣을 본문 조각 또는 표의 한 행."""

    content: str
    table_id: int | None = None
    table_header: str = ""


def _make_text_splitter(chunk_size: int) -> RecursiveCharacterTextSplitter:
    """겹침은 청크를 조립할 때 적용하므로 여기서는 분할만 한다."""
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=0,
        separators=["\n\n", "\n", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )


def _extract_page_title(text: str) -> tuple[str, str]:
    """파서가 붙인 페이지 표시는 제거하고, 첫 절 제목을 분리한다."""
    text = re.sub(
        r"\A## 페이지 \d+[ \t]*(?:\n|$)",
        "",
        text,
        count=1,
    ).strip()

    first_line, _, remaining = text.partition("\n")

    # 현재 매뉴얼의 "01 공통 대응..." 또는 Markdown 제목.
    if remaining.strip() and re.match(r"^(?:#{1,6}\s+|\d{2}\s+)", first_line):
        return first_line.strip(), remaining.strip()

    return "", text


def _make_units(text: str, body_limit: int) -> list[_ChunkUnit]:
    """본문은 크기에 맞춰 나누고, 표는 행 단위로 유지한다."""
    splitter = _make_text_splitter(body_limit)
    units: list[_ChunkUnit] = []

    for block_id, (block_type, content) in enumerate(_split_blocks(text)):
        if block_type == "text":
            units.extend(
                _ChunkUnit(content=part) for part in splitter.split_text(content)
            )
            continue

        lines = content.splitlines()
        header = "\n".join(lines[:2])
        rows = lines[2:]

        if not rows:
            units.append(_ChunkUnit(content=header))
            continue

        units.extend(
            _ChunkUnit(
                content=row,
                table_id=block_id,
                table_header=header,
            )
            for row in rows
        )

    return units


def _render_units(units: list[_ChunkUnit], title: str) -> str:
    """연속된 표 행은 합치고, 청크마다 필요한 표 헤더를 붙인다."""
    blocks: list[str] = []
    previous_table_id: int | None = None

    for unit in units:
        if unit.table_id is None:
            blocks.append(unit.content)
        elif unit.table_id == previous_table_id:
            blocks[-1] += "\n" + unit.content
        else:
            blocks.append(unit.table_header + "\n" + unit.content)

        previous_table_id = unit.table_id

    body = "\n\n".join(blocks)
    return f"{title}\n\n{body}" if title else body


def _overlap_units(
    units: list[_ChunkUnit],
    overlap: int,
) -> list[_ChunkUnit]:
    """본문 끝부분 또는 표의 마지막 행을 다음 청크에 전달한다."""
    if not units or overlap == 0:
        return []

    last = units[-1]

    if last.table_id is not None:
        # 표는 문자 수로 자르지 않고 마지막 행 전체를 반복한다.
        return [last]

    parts = _make_text_splitter(overlap).split_text(last.content)
    return [_ChunkUnit(content=parts[-1])] if parts else []


def chunk_documents(
    documents: list[Document],
    *,
    config: ChunkerConfig | None = None,
) -> list[Document]:
    """같은 페이지의 본문·표를 묶고, 크기를 넘으면 청크를 나눈다.

    페이지 번호는 메타데이터로 유지하고 첫 절 제목은 청크마다 반복한다.
    본문 오버랩은 설정한 문자 수 이내, 표 오버랩은 마지막 행 단위다.
    겹침 때문에 크기를 넘으면 해당 경계의 겹침은 생략한다.
    표 헤더와 한 행만으로 크기를 넘는 경우에는 행 보존을 우선한다.
    """
    config = config or ChunkerConfig()
    chunks: list[Document] = []

    for document in documents:
        title, text = _extract_page_title(document.page_content)
        if not text:
            continue

        title_length = len(title) + 2 if title else 0
        if title_length >= config.chunk_size:
            raise ValueError("chunk_size가 페이지 제목을 담기에 너무 작습니다.")

        # 본문 조각은 다음 청크의 겹침을 넣을 여유를 두고 분할한다.
        body_limit = max(
            1,
            config.chunk_size - title_length - config.chunk_overlap - 2,
        )
        units = _make_units(text, body_limit)

        page_chunks: list[str] = []
        current: list[_ChunkUnit] = []

        for unit in units:
            candidate = [*current, unit]

            if current and len(_render_units(candidate, title)) > config.chunk_size:
                page_chunks.append(_render_units(current, title))

                overlap = _overlap_units(current, config.chunk_overlap)
                candidate = [*overlap, unit]

                # 표 행은 통째로 유지하므로 겹침을 넣을 공간이
                # 부족할 수 있다. 이때는 새 내용을 우선한다.
                if len(_render_units(candidate, title)) > config.chunk_size:
                    candidate = [unit]

            current = candidate

        if current:
            page_chunks.append(_render_units(current, title))

        for chunk_index, content in enumerate(page_chunks):
            metadata = deepcopy(document.metadata)
            metadata["chunk_index"] = chunk_index

            chunks.append(
                Document(
                    page_content=content,
                    metadata=metadata,
                )
            )

    return chunks
