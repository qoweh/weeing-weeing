"""문자열 질문으로 후보를 검색하고, 선택적으로 리랭킹해 Evidence를 반환한다.

처리 흐름: 입력 검증 → 필터 변환 → 하이브리드 검색 → 리랭킹 → 상위 k개 근거 반환.
실제 dense·BM25·RRF 계산은 저장소가, 모델 기반 재정렬은 reranker가 담당한다.
이 파일은 각 단계를 연결하고 문서 본문·출처를 공통 Evidence 형식으로 옮긴다.
Incident를 검색어로 바꾸는 처리는 interface.incident_query(rag/query.py)가 맡는다.
"""

import math
from typing import Any

from weeing_weeing.contracts import Evidence
from weeing_weeing.rag.reranker import Reranker
from weeing_weeing.rag.store import (
    Hit,
    VectorStore,
    Where,
    check_k,
    check_where,
    clean_metadata,
)


def _where(filters: dict[str, Any] | None) -> Where | None:
    """외부 검색 필터를 검증하고 저장소용 Where로 변환하는 내부 보조 함수.

    예: {"code": "BTT2-P03"} → {"codes": "BTT2-P03"}.
    필터가 없으면 None을 반환한다. 원본 딕셔너리는 수정하지 않으며,
    충돌하는 별칭·빈 리스트·None 등 유효하지 않은 조건은 예외로 알린다.
    """
    if not filters:
        return None

    # 원본 filters가 변경되지 않도록 복사한다.
    where = dict(filters)

    # 외부에서 받은 code 필터를 저장소 필드명인 codes로 변환한다.
    if "code" in where:
        if "codes" in where:
            raise ValueError("filters에는 code와 codes 중 하나만 넣습니다.")
        where["codes"] = where.pop("code")

    # 필터 형식을 검증하고 None 값이 포함되지 않았는지 확인한다.
    check_where(where)

    if any(value is None for value in where.values()):
        raise ValueError("filters 값에 None을 넣을 수 없습니다.")

    # 저장소에 전달할 수 있도록 메타데이터를 정리한다.
    return clean_metadata(where)


def _citation(hit: Hit) -> str:
    """검색 결과 한 건의 사람이 읽을 수 있는 인용 문자열을 만드는 보조 함수.

    청크에 저장된 citation을 우선 사용한다. 없으면 문서 ID·버전에 저장된
    절·페이지 정보를 덧붙인다. 반환값은 Evidence.citation에 들어간다.
    """
    chunk = hit.chunk
    citation = chunk.metadata.get("citation")

    # 유효한 citation이 저장되어 있다면 그대로 사용한다.
    if isinstance(citation, str) and citation.strip():
        return citation

    # 저장된 정보만 사용하며, 없는 절이나 페이지는 추측하지 않는다.
    parts = [chunk.doc_id, chunk.doc_version]

    section = chunk.metadata.get("section")
    if isinstance(section, str) and section.strip():
        parts.append(section)

    page = chunk.metadata.get("page")
    if page is not None:
        parts.append(f"p.{page}")

    return " ".join(parts)


def _evidence(hit: Hit) -> Evidence:
    """저장소의 Hit 한 건을 Agent가 인용할 공통 계약 Evidence로 변환한다.

    청크 ID·문서 ID·버전·본문·절·RRF 점수를 복사하고 _citation()으로 출처를 붙인다.
    이 함수는 검색 순위를 계산하거나 본문 내용을 새로 생성하지 않는다.
    """
    chunk = hit.chunk

    return Evidence(
        evidence_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        doc_version=chunk.doc_version,
        section=chunk.metadata.get("section"),
        text=chunk.text,
        score=hit.score,
        citation=_citation(hit),
        relevance=hit.relevance,
    )


class HybridRetriever:
    """하이브리드 검색 결과를 Evidence 목록으로 제공한다.

    dense 검색, BM25 검색, RRF 순위 결합은 VectorStore에서 처리한다.
    reranker가 있으면 후보를 넓혀 검색한 뒤 재정렬하고 최종 k개를 선택한다.
    Evidence.score는 재정렬 후에도 저장소의 RRF 점수를 유지한다.
    모델 점수는 Evidence.relevance로 전달하고 min_relevance가 있으면 미달 근거를 뺀다.
    VectorStore의 생성과 종료는 이 클래스를 사용하는 호출자가 담당한다.
    """

    def __init__(
        self,
        store: VectorStore,
        *,
        reranker: Reranker | None = None,
        candidate_k: int = 30,
        min_relevance: float | None = None,
    ) -> None:
        """저장소와 선택적 리랭커를 주입받고 리랭킹 후보 수를 검증한다.

        store는 이미 조립된 저장소 객체다. reranker=None이면 RRF 순위를 사용한다.
        candidate_k는 리랭킹에 넘길 최소 후보 수이며 search()의 최종 k와 구분한다.
        min_relevance=None이면 거르지 않는다. 하한을 지정하려면 reranker가 필요하다.
        하한은 모델별 평가로 정하며, 모델 출력이 하한과 같으면 포함한다.
        """
        if isinstance(candidate_k, bool) or not isinstance(candidate_k, int):
            raise TypeError("candidate_k는 정수여야 합니다.")
        check_k(candidate_k)
        if min_relevance is not None:
            if isinstance(min_relevance, bool) or not isinstance(
                min_relevance, (int, float)
            ):
                raise TypeError("min_relevance는 유한한 숫자 또는 None이어야 합니다.")
            if not math.isfinite(min_relevance):
                raise ValueError("min_relevance에 NaN 또는 무한대를 넣을 수 없습니다.")
            if reranker is None:
                raise ValueError("min_relevance를 사용하려면 리랭커가 필요합니다.")
        self._store = store
        self._reranker = reranker
        self._candidate_k = candidate_k
        self._min_relevance = min_relevance

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        """질문과 필터로 검색하고 결과를 Evidence 목록으로 반환한다.

        Args:
            query: 검색할 질문 또는 문장.
            k: 반환할 검색 결과의 최대 개수.
            filters: 검색 범위를 제한할 메타데이터 필터.

        Returns:
            관련도 순 Evidence 목록. 리랭킹 시에도 score는 원래의 RRF 점수다.

        Raises:
            ValueError: query가 비어 있거나 필터 또는 k 값이 유효하지 않은 경우.
            TypeError: k가 정수가 아닌 경우.
        """
        # 빈 문자열이나 공백만 있는 검색어는 허용하지 않는다.
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query는 비어 있지 않은 문자열이어야 합니다.")

        # bool은 Python에서 int의 하위 타입이므로 별도로 제외한다.
        if isinstance(k, bool) or not isinstance(k, int):
            raise TypeError("k는 정수여야 합니다.")

        # 결과 개수와 필터를 검증한 뒤 하이브리드 검색을 실행한다.
        check_k(k)
        where = _where(filters)
        # 예: 최종 5개를 반환해도 후보 30개를 재정렬해야 하위 후보가 올라올 수 있다.
        # k가 후보 설정보다 크면 k개까지 확보하고, 리랭킹을 끄면 기존 k개만 검색한다.
        candidate_k = max(k, self._candidate_k) if self._reranker is not None else k
        hits = self._store.hybrid_query(query, k=candidate_k, where=where)
        # 빈 결과에서는 모델을 로드하지 않는다. 리랭킹 실패는 호출자에게 예외로 전달된다.
        if hits and self._reranker is not None:
            hits = self._reranker.rerank(query, hits)

        if self._min_relevance is not None:
            # 점수 누락·오류를 근거 없음으로 숨기거나 RRF로 대신 판정하지 않는다.
            if any(
                hit.relevance is None or not math.isfinite(hit.relevance)
                for hit in hits
            ):
                raise ValueError(
                    "관련도 필터에 필요한 리랭커 점수가 없습니다/유효하지 않습니다."
                )
            hits = [hit for hit in hits if hit.relevance >= self._min_relevance]

        # 최종 순위에서 k개만 고른 뒤 공통 근거 형식으로 변환한다.
        return [_evidence(hit) for hit in hits[:k]]
