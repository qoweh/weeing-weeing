"""검색된 후보를 질문·본문의 관련도로 다시 정렬하는 rag 내부 구현.

Retriever가 후보 Hit 목록을 넘기면 CrossEncoder가 질문·청크 본문 쌍마다 점수를 낸다.
이 점수는 Hit.relevance로 전달하고, 원래 Hit의 본문·출처·RRF 점수는 보존한다.
최종 반환 개수 k를 선택하고 Evidence로 바꾸는 일은 retriever.py가 담당한다.
"""

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

from weeing_weeing.rag.store import Hit


class Reranker(Protocol):
    """교체 가능한 리랭커가 제공해야 할 메서드 형태를 정의하는 계약.

    Protocol은 정렬 구현이 아니다. Retriever는 이 계약을 따르는 객체를 주입받아
    실제 모델 종류와 관계없이 rerank()를 호출할 수 있다.
    """

    def rerank(self, query: str, hits: Sequence[Hit]) -> list[Hit]:
        """관련도 순으로 반환하며 relevance에 모델 점수를 담는다. RRF는 보존한다."""
        ...


class PairScorer(Protocol):
    """질문·본문 쌍을 관련도 점수로 바꾸는 모델의 호출 형태.

    CrossEncoder가 이 역할을 하며, 반환 점수는 입력 쌍과 같은 순서로 대응한다.
    """

    def predict(
        self,
        sentences: list[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
    ) -> Sequence[float]:
        """(질문, 본문) 목록을 배치 단위로 평가해 각 쌍의 점수 하나를 반환한다."""
        ...


def _load_model(model_name: str) -> PairScorer:
    """준비된 로컬 경로·캐시에서 단일 점수 출력 CrossEncoder를 로드한다.

    호출 시점에 라이브러리를 import해 검색기를 만들기만 할 때의 로드 비용을 피한다.
    다중 분류 모델은 점수 하나로 정렬할 수 없으므로 거부하고, 로드 실패는 전달한다.
    """
    from sentence_transformers import CrossEncoder

    # 추론 중 다운로드 없이 로컬 경로 또는 미리 받은 캐시에서만 읽는다.
    model = CrossEncoder(model_name, local_files_only=True, trust_remote_code=False)
    if model.num_labels != 1:
        raise ValueError("리랭커는 질문·본문 쌍마다 점수 하나를 출력해야 합니다.")
    return model


class CrossEncoderReranker:
    """로컬 CrossEncoder를 첫 리랭킹 때 로드하고 재사용한다.

    점수는 relevance로 전달한다. 동점이면 입력의 RRF 순위를 유지하며,
    모델 로드·추론 실패는 예외로 전달한다(검색 결과 없음으로 숨기지 않는다).
    """

    def __init__(self, model_name: str, *, batch_size: int = 16) -> None:
        """모델 이름과 배치 크기를 검증하고, 실제 모델 로드는 첫 사용까지 미룬다.

        model_name은 로컬 디렉터리 또는 캐시된 모델 ID다.
        batch_size는 predict()가 한 번에 처리하는 질문·본문 쌍의 개수다.
        """
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name은 비어 있지 않은 문자열이어야 합니다.")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int):
            raise TypeError("batch_size는 정수여야 합니다.")
        if batch_size < 1:
            raise ValueError("batch_size는 1 이상이어야 합니다.")
        self._model_name = model_name.strip()
        self._batch_size = batch_size
        # None은 아직 모델을 올리지 않았다는 뜻이다. 로드한 모델은 다음 호출에 재사용한다.
        self._model: PairScorer | None = None

    def rerank(self, query: str, hits: Sequence[Hit]) -> list[Hit]:
        """질문과 각 후보 본문을 채점해 관련도 내림차순의 새 Hit 목록을 반환한다.

        입력 후보는 수정하지 않는다. 후보가 없으면 모델 호출 없이 []를 반환한다.
        모델 출력 개수나 수치가 잘못되면 예외로 알린다.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query는 비어 있지 않은 문자열이어야 합니다.")
        if not hits:
            return []
        if self._model is None:
            self._model = _load_model(self._model_name)
        # 같은 질문에 후보 본문을 하나씩 짝지어, 청크마다 관련도 점수 하나를 받는다.
        raw = self._model.predict(
            [(query, hit.chunk.text) for hit in hits],
            batch_size=self._batch_size,
            show_progress_bar=False,
        )
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
