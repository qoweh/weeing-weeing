"""실제 API 호출 없이(httpx.MockTransport) 리랭크 정렬·출처 보존·실패 처리를 검증한다."""

import json

import httpx
import pytest

from weeing_weeing.rag.embedder import EmbeddingApiError
from weeing_weeing.rag.reranker import VoyageReranker
from weeing_weeing.rag.store import Chunk, Hit

KEY = "test-voyage-key"


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)


def hits():
    return [
        Hit(Chunk(f"MAN:1:{i:04d}", "MAN", "1", text, {"citation": text}), score)
        for i, (text, score) in enumerate(
            [("속도 점검", 0.03), ("광전 센서 오염", 0.02), ("에너지 격리", 0.01)]
        )
    ]


def client(scores=None, *, status=200, body=None, requests=None):
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if requests is not None:
            requests.append((request, payload))
        if body is not None:
            return httpx.Response(status, json=body)
        values = scores if scores is not None else [0.0] * len(payload["documents"])
        data = [{"index": i, "relevance_score": s} for i, s in enumerate(values)]
        data.sort(key=lambda item: -item["relevance_score"])  # API는 점수 순으로 준다
        return httpx.Response(
            status, json={"data": data, "usage": {"total_tokens": 42}}
        )

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_sorts_by_api_score_and_preserves_rrf():
    requests = []
    ranker = VoyageReranker(
        "rerank-3-lite", client=client([0.1, 0.9, 0.5], requests=requests)
    )
    candidates = hits()
    found = ranker.rerank("센서 오염", candidates)
    assert [h.chunk for h in found] == [candidates[i].chunk for i in (1, 2, 0)]
    assert [h.score for h in found] == [candidates[i].score for i in (1, 2, 0)]
    assert [h.relevance for h in found] == [0.9, 0.5, 0.1]
    assert all(h.relevance is None for h in candidates)  # 원본 후보는 수정하지 않음
    request, payload = requests[0]
    assert payload == {
        "query": "센서 오염",
        "documents": [h.chunk.text for h in candidates],
        "model": "rerank-3-lite",
        "truncation": True,
    }
    assert request.url.path.endswith("/rerank")
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert ranker.total_tokens == 42


def test_results_key_from_sdk_shape_is_accepted():
    body = {"results": [{"index": 0, "relevance_score": 0.2}]}
    found = VoyageReranker("r", client=client(body=body)).rerank("질문", hits()[:1])
    assert [h.relevance for h in found] == [0.2]


def test_batches_candidates_by_batch_size():
    requests = []
    ranker = VoyageReranker("r", batch_size=2, client=client(requests=requests))
    assert len(ranker.rerank("질문", hits())) == 3
    assert [len(p["documents"]) for _, p in requests] == [2, 1]


def test_tied_scores_keep_hybrid_order():
    candidates = hits()
    found = VoyageReranker("r", client=client([0.0, 0.0, 0.0])).rerank(
        "질문", candidates
    )
    assert [h.chunk for h in found] == [h.chunk for h in candidates]


def test_no_candidates_does_not_call_api():
    requests = []
    assert (
        VoyageReranker("r", client=client(requests=requests)).rerank("질문", []) == []
    )
    assert requests == []


@pytest.mark.parametrize(
    "body",
    [
        {"data": [{"index": 0, "relevance_score": 0.1}]},  # 개수 부족
        {"data": [{"index": 5, "relevance_score": 0.1}]},  # 범위 밖 index
        {"data": [{"index": 0, "relevance_score": None}]},
        {"data": [{"index": i, "relevance_score": float("nan")} for i in range(3)]},
        {"unexpected": []},
    ],
)
def test_invalid_api_scores_are_rejected(body):
    with pytest.raises(ValueError):
        VoyageReranker("r", client=client(body=body)).rerank("질문", hits())


def test_api_failure_is_not_no_evidence():
    ranker = VoyageReranker("r", client=client(status=401, body={"detail": "bad key"}))
    with pytest.raises(EmbeddingApiError, match="HTTP 401") as error:
        ranker.rerank("질문", hits())
    assert KEY not in str(error.value)


def test_missing_key_is_clear_error(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY")
    with pytest.raises(EmbeddingApiError, match="VOYAGE_API_KEY"):
        VoyageReranker("r", client=client()).rerank("질문", hits())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model_name": " "},
        {"batch_size": 0},
        {"batch_size": 1001},
        {"batch_size": True},
        {"batch_size": 1.5},
    ],
)
def test_invalid_configuration(kwargs):
    with pytest.raises((ValueError, TypeError)):
        VoyageReranker(**{"model_name": "r", **kwargs})
