"""저장소의 하이브리드 검색 결과를 Agent가 인용할 Evidence로 변환한다."""

from typing import Any

from weeing_weeing.contracts import Evidence
from weeing_weeing.rag.store import (
    Hit,
    VectorStore,
    Where,
    check_k,
    check_where,
    clean_metadata,
)


def _where(filters: dict[str, Any] | None) -> Where | None:
    if not filters:
        return None
    where = dict(filters)
    if "code" in where:
        if "codes" in where:
            raise ValueError("filters에는 code와 codes 중 하나만 넣습니다.")
        where["codes"] = where.pop("code")
    check_where(where)
    if any(value is None for value in where.values()):
        raise ValueError("filters 값에 None을 넣을 수 없습니다.")
    return clean_metadata(where)


def _evidence(hit: Hit) -> Evidence:
    chunk = hit.chunk
    section = chunk.metadata.get("section")
    citation = chunk.metadata.get("citation")
    if not isinstance(citation, str) or not citation.strip():
        # 저장된 출처만 사용한다. 절·페이지가 없으면 추측해서 채우지 않는다.
        parts = [chunk.doc_id, chunk.doc_version]
        if isinstance(section, str) and section.strip():
            parts.append(section)
        page = chunk.metadata.get("page")
        if page is not None:
            parts.append(f"p.{page}")
        citation = " ".join(parts)
    return Evidence(
        evidence_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        doc_version=chunk.doc_version,
        section=section,
        text=chunk.text,
        score=hit.score,
        citation=citation,
    )


class HybridRetriever:
    """Retriever 구현. 프로세스에서 재사용하는 VectorStore를 주입한다.

    저장소가 dense·BM25·RRF를 처리하며 여기서는 그 순위와 점수를 유지한다.
    연결의 생성·종료는 저장소를 조립한 호출자가 맡는다.
    """

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    def search(
        self, query: str, *, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query는 비어 있지 않은 문자열이어야 합니다.")
        if isinstance(k, bool) or not isinstance(k, int):
            raise TypeError("k는 정수여야 합니다.")
        check_k(k)
        hits = self._store.hybrid_query(query, k=k, where=_where(filters))
        return [_evidence(hit) for hit in hits]
