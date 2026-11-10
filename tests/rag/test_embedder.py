"""임베더 단위 테스트. 외부 호출은 httpx.MockTransport로 대신한다(실제 키·비용 없음)."""

import json
import math

import httpx
import pytest

from weeing_weeing.rag.embedder import (
    VOYAGE_BASE_URL,
    VOYAGE_BATCH,
    EmbeddingApiError,
    HashingEmbedder,
    VoyageEmbedder,
)

KEY = "test-voyage-key"


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


# --- hashing ---


def test_hashing_is_deterministic_normalized_and_keyword_sensitive():
    embedder = HashingEmbedder(256)
    a, b, c = embedder.embed_documents(
        [
            "입구 광전센서 차단으로 트레이 걸림",
            "모터 베어링 진동 상한",
            "입구 광전센서 오염",
        ]
    )
    assert len(a) == 256
    assert math.isclose(math.sqrt(sum(v * v for v in a)), 1.0)
    assert embedder.embed_query("입구 광전센서 차단으로 트레이 걸림") == a
    query = embedder.embed_query("광전센서 차단")
    assert cosine(query, a) > cosine(query, b)
    assert cosine(query, c) > cosine(query, b)


def test_hashing_text_without_tokens_is_not_zero_vector():
    vec = HashingEmbedder(16, tokenize=lambda text: []).embed_query("")
    assert vec[0] == 1.0 and sum(abs(v) for v in vec) == 1.0


def test_hashing_rejects_tiny_dim():
    with pytest.raises(ValueError):
        HashingEmbedder(4)


# --- voyage ---


def voyage_client(*, responses=None, requests=None, dim=4):
    """responses: 순서대로 돌려줄 (status, body) 목록. 없으면 정상 벡터."""
    queue = list(responses or [])

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if requests is not None:
            requests.append((request, payload))
        if queue:
            status, body = queue.pop(0)
            if isinstance(body, Exception):
                raise body
            if isinstance(body, str):  # JSON 표준 밖 값(NaN 등)을 그대로 보낸다
                return httpx.Response(status, content=body.encode())
            return httpx.Response(status, json=body)
        data = [
            {"index": i, "embedding": [float(i + 1)] * dim}
            for i in range(len(payload["input"]))
        ]
        data.reverse()  # index 순으로 다시 맞추는지 확인한다
        return httpx.Response(
            200, json={"data": data, "usage": {"total_tokens": len(data)}}
        )

    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)


def test_voyage_sends_input_type_and_dimension(api_key):
    requests = []
    embedder = VoyageEmbedder(
        "voyage-4-lite", dim=512, client=voyage_client(requests=requests)
    )
    docs = embedder.embed_documents(["가", "나"])
    query = embedder.embed_query("다")
    assert docs == [[1.0] * 4, [2.0] * 4]
    assert query == [1.0] * 4
    (doc_req, doc_payload), (_, query_payload) = requests
    assert doc_req.url == f"{VOYAGE_BASE_URL}/embeddings"
    assert doc_req.headers["Authorization"] == f"Bearer {KEY}"
    assert doc_payload == {
        "input": ["가", "나"],
        "model": "voyage-4-lite",
        "input_type": "document",
        "output_dimension": 512,
        "truncation": True,
    }
    assert query_payload["input_type"] == "query"
    assert embedder.total_tokens == 3


def test_voyage_applies_timeout_to_injected_client(api_key):
    requests = []
    embedder = VoyageEmbedder(
        "m", timeout_s=7.5, client=voyage_client(requests=requests)
    )
    embedder.embed_query("q")
    ((request, _),) = requests
    assert request.extensions["timeout"] == {
        "connect": 7.5,
        "read": 7.5,
        "write": 7.5,
        "pool": 7.5,
    }


def test_voyage_batches_large_inputs(api_key):
    requests = []
    embedder = VoyageEmbedder("m", client=voyage_client(requests=requests))
    texts = [f"t{i}" for i in range(VOYAGE_BATCH + 1)]
    assert len(embedder.embed_documents(texts)) == len(texts)
    assert [len(p["input"]) for _, p in requests] == [VOYAGE_BATCH, 1]
    assert embedder.embed_documents([]) == []


def test_voyage_retries_rate_limit_then_succeeds(api_key, monkeypatch):
    sleeps = []
    monkeypatch.setattr("weeing_weeing.rag.embedder.time.sleep", sleeps.append)
    client = voyage_client(
        responses=[(429, {"detail": "rate"}), (503, {"detail": "busy"})]
    )
    assert VoyageEmbedder("m", client=client).embed_query("q") == [1.0] * 4
    assert sleeps == [1, 2]


def test_voyage_gives_up_after_retries(api_key, monkeypatch):
    monkeypatch.setattr("weeing_weeing.rag.embedder.time.sleep", lambda s: None)
    client = voyage_client(responses=[(500, {"detail": "x"})] * 3)
    with pytest.raises(EmbeddingApiError, match="HTTP 500"):
        VoyageEmbedder("m", client=client).embed_query("q")


def test_voyage_connection_error_is_wrapped(api_key, monkeypatch):
    monkeypatch.setattr("weeing_weeing.rag.embedder.time.sleep", lambda s: None)
    error = httpx.ConnectError("down")
    client = voyage_client(responses=[(0, error)] * 3)
    with pytest.raises(EmbeddingApiError, match="연결 실패"):
        VoyageEmbedder("m", client=client).embed_query("q")


def test_voyage_auth_error_is_not_retried_and_hides_key(api_key):
    requests = []
    client = voyage_client(responses=[(401, {"detail": "bad"})], requests=requests)
    with pytest.raises(EmbeddingApiError, match="HTTP 401") as error:
        VoyageEmbedder("m", client=client).embed_query("q")
    assert len(requests) == 1
    assert KEY not in str(error.value)


@pytest.mark.parametrize(
    "body",
    [
        {"nope": 1},
        {"data": []},
        {"data": [{"index": 0, "embedding": []}]},
        '{"data": [{"index": 0, "embedding": [NaN]}]}',
    ],
)
def test_voyage_invalid_response_is_rejected(api_key, body):
    client = voyage_client(responses=[(200, body)])
    with pytest.raises(EmbeddingApiError):
        VoyageEmbedder("m", client=client).embed_query("q")


def test_voyage_missing_key_fails_before_request(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    requests = []
    with pytest.raises(EmbeddingApiError, match="VOYAGE_API_KEY"):
        VoyageEmbedder("m", client=voyage_client(requests=requests)).embed_query("q")
    assert requests == []


@pytest.mark.parametrize("kwargs", [{"model": " "}, {"dim": 300}])
def test_voyage_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        VoyageEmbedder(**{"model": "m", **kwargs})
