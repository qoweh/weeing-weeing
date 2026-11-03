"""조항·대응 사례 경계를 인식하는 문서 청킹."""

import re
from copy import deepcopy

from langchain_core.documents import Document

from weeing_weeing.rag.chunker import ChunkerConfig, chunk_documents

_ARTICLE = re.compile(r"^제\s*\d+\s*조\s*\([^\n)]+\)")
_CASE = re.compile(
    r"^(?:BTT2-)?[PMD]\d{2}(?:\s*/\s*(?:BTT2-)?[PMD]\d{2})*\s*[-–—]\s*\S"
)


def _heading(line: str) -> bool:
    return bool(_ARTICLE.match(line) or _CASE.match(line))


def structured_chunk_documents(
    documents: list[Document], *, config: ChunkerConfig | None = None
) -> list[Document]:
    """페이지 내 제목 경계로 먼저 나눈 뒤, 긴 구간은 기존 분할기를 사용한다.

    구조를 인식하지 못하는 구간은 기존 방식으로 처리한다. 페이지 간 연결이나
    모든 문서 형식의 구조 인식은 지원하지 않는다.
    """
    config = config or ChunkerConfig()
    result: list[Document] = []
    for page in documents:
        context = " > ".join(
            str(value)
            for value in (page.metadata.get("doc_id"), page.metadata.get("section"))
            if value
        )
        prefix = f"문맥: {context}\n\n" if context else ""
        available_page = config.chunk_size - len(prefix)
        if available_page <= 0:
            raise ValueError("청크 크기가 문맥 머리줄보다 작습니다.")
        page_config = ChunkerConfig(
            chunk_size=available_page,
            chunk_overlap=min(config.chunk_overlap, available_page - 1),
        )
        page_result: list[Document] = []
        text = re.sub(r"\A## 페이지 \d+[ \t]*(?:\n|$)", "", page.page_content).strip()
        lines = text.splitlines()
        boundaries = [i for i, line in enumerate(lines) if _heading(line.strip())]
        if not boundaries:
            page_result.extend(chunk_documents([page], config=page_config))
            for part in page_result:
                part.page_content = prefix + part.page_content
            result.extend(page_result)
            continue

        starts = ([0] if boundaries[0] else []) + boundaries
        for pos, start in enumerate(starts):
            end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
            block = "\n".join(lines[start:end]).strip()
            if not block:
                continue
            if start not in boundaries and block == page.metadata.get("section"):
                continue
            heading = lines[start].strip() if start in boundaries else None
            metadata = deepcopy(page.metadata)
            if heading:
                metadata["structural_heading"] = heading
            # 헤더를 분리해 본문과 함께 유지하고, 여러 조각이면 각 조각에 반복한다.
            if heading:
                body = "\n".join(lines[start + 1 : end]).strip()
                if not body:
                    # 제목만 있는 구간도 누락하지 않는다. 검토 시 확인할 수 있다.
                    page_result.append(
                        Document(page_content=heading, metadata=metadata)
                    )
                    continue
                available = page_config.chunk_size - len(heading) - 2
                if available <= 0:
                    raise ValueError("청크 크기가 구조 제목보다 작습니다.")
                inner = ChunkerConfig(
                    chunk_size=available,
                    chunk_overlap=min(page_config.chunk_overlap, available - 1),
                )
                parts = chunk_documents(
                    [Document(page_content=body, metadata=metadata)], config=inner
                )
                for part in parts:
                    part.page_content = f"{heading}\n\n{part.page_content}"
                page_result.extend(parts)
            else:
                page_result.extend(
                    chunk_documents(
                        [Document(page_content=block, metadata=metadata)],
                        config=page_config,
                    )
                )
        for part in page_result:
            part.page_content = prefix + part.page_content
        result.extend(page_result)
    return result
