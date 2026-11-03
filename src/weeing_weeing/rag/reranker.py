"""검색된 후보를 질문·본문의 관련도로 다시 정렬하는 rag 내부 구현.

Retriever가 후보 Hit 목록을 넘기면 리랭크 API(Voyage)가 질문·청크 본문 쌍마다 점수를 낸다.
RERANKER_MODEL이 비어 있으면 리랭커를 만들지 않고 RRF 순위를 그대로 쓴다(기본, 비용 0).
이 점수는 Hit.relevance로 전달하고, 원래 Hit의 본문·출처·RRF 점수는 보존한다.
최종 반환 개수 k를 선택하고 Evidence로 바꾸는 일은 retriever.py가 담당한다.
"""

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

import httpx

from weeing_weeing.rag.embedder import VOYAGE_BASE_URL, voyage_post
from weeing_weeing.rag.store import Hit


class Reranker(Protocol):
    """교체 가능한 리랭커가 제공해야 할 메서드 형태를 정의하는 계약.

    Protocol은 정렬 구현이 아니다. Retriever는 이 계약을 따르는 객체를 주입받아
    실제 모델 종류와 관계없이 rerank()를 호출할 수 있다.
    """

    def rerank(self, query: str, hits: Sequence[Hit]) -> list[Hit]:
        """관련도 순으로 반환하며 relevance에 모델 점수를 담는다. RRF는 보존한다."""
        ...


class VoyageReranker:
    """Voyage AI 리랭크 API로 질문·후보 본문의 관련도를 매긴다(로컬 모델 없음).

    점수(0~1)는 relevance로 전달한다. 동점이면 입력의 RRF 순위를 유지하며,
    API 호출·응답 형식 실패는 예외로 전달한다(검색 결과 없음으로 숨기지 않는다).
    """

    def __init__(
        self,
        model_name: str,
        *,
        batch_size: int = 100,
        base_url: str = VOYAGE_BASE_URL,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        """batch_size는 한 요청에 넣는 후보 본문 수다(API 상한 1,000)."""
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name은 비어 있지 않은 문자열이어야 합니다.")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int):
            raise TypeError("batch_size는 정수여야 합니다.")
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size는 1 이상 1000 이하여야 합니다.")
        self._model_name = model_name.strip()
        self._batch_size = batch_size
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._client = client
        self.total_tokens = 0  # 이 프로세스에서 쓴 리랭크 토큰(비용 확인용)

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        data = voyage_post(
            "rerank",
            {
                "query": query,
                "documents": texts,
                "model": self._model_name,
                "truncation": True,
            },
            base_url=self._base_url,
            timeout_s=self._timeout_s,
            client=self._client,
        )
        # REST 응답은 data[], Python SDK 문서는 results[]로 적는다. 둘 다 받는다.
        items = (
            data.get("data", data.get("results")) if isinstance(data, dict) else None
        )
        if not isinstance(items, list):
            raise ValueError("리랭커 응답에 결과 목록이 없습니다.")
        scores: list[float | None] = [None] * len(texts)
        for item in items:
            index = item.get("index") if isinstance(item, dict) else None
            if not isinstance(index, int) or not 0 <= index < len(texts):
                raise ValueError("리랭커 응답의 index가 잘못됐습니다.")
            score = item.get("relevance_score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ValueError("리랭커 응답의 relevance_score가 숫자가 아닙니다.")
            scores[index] = float(score)
        usage = data.get("usage")
        if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
            self.total_tokens += usage["total_tokens"]
        if any(score is None for score in scores):
            raise ValueError("리랭커 점수 개수가 검색 후보 개수와 다릅니다.")
        return scores  # type: ignore[return-value]

    def rerank(self, query: str, hits: Sequence[Hit]) -> list[Hit]:
        """질문과 각 후보 본문을 채점해 관련도 내림차순의 새 Hit 목록을 반환한다.

        입력 후보는 수정하지 않는다. 후보가 없으면 API 호출 없이 []를 반환한다.
        모델 출력 개수나 수치가 잘못되면 예외로 알린다.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query는 비어 있지 않은 문자열이어야 합니다.")
        if not hits:
            return []
        raw: list[float] = []
        for start in range(0, len(hits), self._batch_size):
            batch = hits[start : start + self._batch_size]
            raw.extend(self._scores(query, [hit.chunk.text for hit in batch]))
        # 모든 후보에 정상 점수가 있어야 순위를 신뢰할 수 있다.
        if len(raw) != len(hits):
            raise ValueError("리랭커 점수 개수가 검색 후보 개수와 다릅니다.")
        scores = [float(score) for score in raw]
        if not all(math.isfinite(score) for score in scores):
            raise ValueError("리랭커 점수에 NaN 또는 무한대가 있습니다.")
        # 후보 자체 대신 인덱스를 정렬한다. Python의 안정 정렬은 동점의 입력 순서를 유지한다.
        order = sorted(range(len(hits)), key=lambda i: scores[i], reverse=True)
        # 원본은 수정하지 않고 모델 점수만 덧붙인다. 청크·출처·RRF는 유지한다.
        return [replace(hits[i], relevance=scores[i]) for i in order]
