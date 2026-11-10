"""문서·질문을 dense 벡터로 바꾸는 임베더. 로컬 모델 가중치는 쓰지 않는다.

EMBEDDING_PROVIDER로 고른다(docs/EMBEDDING_API.md).
- hashing(기본): 형태소 토큰을 해시해 고정 차원 벡터로 만든다. 외부 호출·토큰 비용 0.
  의미 유사도는 없고 키워드가 겹칠수록 가깝다. 성능보다 비용이 우선일 때 쓴다.
- voyage: Voyage AI(MongoDB) 임베딩 API. VOYAGE_API_KEY가 필요하고 본문이 외부로 나간다
  (docs/AI_DATA_SECURITY.md).

모델 이름(+차원)은 저장소가 컬렉션에 기록한다. 공급자·모델·차원을 바꾸면 새 컬렉션에서
문서를 다시 등록해야 한다(StoreMismatchError).
"""

import hashlib
import math
import os
import time
from collections import Counter
from collections.abc import Callable, Sequence

import httpx

PROVIDERS = ("hashing", "voyage")
DEFAULT_MODELS = {"hashing": "hashing-kiwi-v1", "voyage": "voyage-4-lite"}
HASHING_DIMS = 1024
VOYAGE_DIMS = (256, 512, 1024, 2048)
# 팀 키는 Voyage 대시보드에서 받는다. MongoDB Atlas 키는 https://ai.mongodb.com/v1
VOYAGE_BASE_URL = "https://api.voyageai.com/v1"
# 한 요청에 넣는 문장 수. API 상한(1,000개)보다 작게 둬 요청당 토큰 상한도 넘지 않게 한다.
VOYAGE_BATCH = 128
# 429·5xx·연결 오류는 이 횟수만큼 다시 시도한다. 그래도 실패하면 예외로 알린다.
VOYAGE_RETRIES = 2


class EmbeddingApiError(RuntimeError):
    """외부 임베딩·리랭크 API 호출이 실패했다(키 없음·인증·한도·네트워크·응답 형식)."""


class HashingEmbedder:
    """Kiwi 형태소 토큰을 부호 있는 해시로 dim칸에 더한 뒤 L2 정규화한다.

    토큰 빈도는 1 + ln(tf)로 줄여 반복어가 벡터를 독차지하지 않게 한다. 토큰이 없으면
    0 벡터 대신 고정 칸 하나를 쓴다(cosine 거리에서 0 벡터는 정의되지 않는다).
    """

    def __init__(
        self,
        dim: int = HASHING_DIMS,
        *,
        tokenize: Callable[[str], list[str]] | None = None,
    ) -> None:
        if dim < 8:
            raise ValueError("dim은 8 이상이어야 한다")
        self.dim = dim
        self._tokenize = tokenize

    def _tokens(self, text: str) -> list[str]:
        if self._tokenize is None:
            # Kiwi 로드는 비싸서 첫 임베딩 때 한 번만 한다(sparse 인코더와 공유).
            from weeing_weeing.rag.sparse import KiwiBm25Encoder

            self._tokenize = KiwiBm25Encoder().tokenize
        return self._tokenize(text)

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token, tf in Counter(self._tokens(text)).items():
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4]) % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign * (1.0 + math.log(tf))
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _api_key(env_name: str = "VOYAGE_API_KEY") -> str:
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise EmbeddingApiError(
            f"{env_name}가 비어 있다. .env에 키를 넣거나 EMBEDDING_PROVIDER=hashing을 쓴다"
        )
    return key


def voyage_post(
    path: str,
    payload: dict,
    *,
    base_url: str,
    timeout_s: float,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict:
    """Voyage API에 POST하고 JSON을 돌려준다. 키는 로그·예외 메시지에 넣지 않는다."""
    headers = {"Authorization": f"Bearer {_api_key()}"}
    sleep = sleep or time.sleep
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    owns = client is None
    http = client or httpx.Client(timeout=timeout_s)
    try:
        for attempt in range(VOYAGE_RETRIES + 1):
            last = attempt == VOYAGE_RETRIES
            try:
                # 주입한 client의 기본 타임아웃과 무관하게 요청마다 제한을 건다.
                response = http.post(
                    url, json=payload, headers=headers, timeout=timeout_s
                )
            except httpx.HTTPError as exc:
                if last:
                    raise EmbeddingApiError(
                        f"Voyage API 연결 실패: {type(exc).__name__}"
                    ) from exc
                sleep(2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if not last:
                    sleep(2**attempt)
                    continue
            if response.status_code >= 400:
                raise EmbeddingApiError(
                    f"Voyage API 오류 HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise EmbeddingApiError("Voyage API 응답이 JSON이 아니다") from exc
        raise AssertionError("unreachable")  # pragma: no cover
    finally:
        if owns:
            http.close()


def _vectors(data: object, count: int) -> list[list[float]]:
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise EmbeddingApiError("Voyage 임베딩 응답에 data 목록이 없다")
    items = sorted(data["data"], key=lambda item: item.get("index", 0))
    if len(items) != count:
        raise EmbeddingApiError(
            f"Voyage 임베딩 개수가 입력과 다르다: {len(items)} != {count}"
        )
    vectors = []
    for item in items:
        vector = item.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise EmbeddingApiError("Voyage 임베딩 응답에 벡터가 없다")
        values = [float(v) for v in vector]
        if not all(math.isfinite(v) for v in values):
            raise EmbeddingApiError("Voyage 임베딩에 NaN·무한대가 있다")
        vectors.append(values)
    return vectors


class VoyageEmbedder:
    """Voyage 임베딩 API. 문서는 input_type=document, 질문은 query로 보낸다."""

    def __init__(
        self,
        model: str,
        *,
        dim: int = 1024,
        base_url: str = VOYAGE_BASE_URL,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("Voyage 임베딩 모델 이름이 비어 있다")
        if dim not in VOYAGE_DIMS:
            raise ValueError(f"Voyage 출력 차원은 {VOYAGE_DIMS} 중 하나다: {dim}")
        self.model = model.strip()
        self.dim = dim
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._client = client
        self.total_tokens = 0  # 이 프로세스에서 쓴 임베딩 토큰(비용 확인용)

    def _embed(self, texts: Sequence[str], input_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), VOYAGE_BATCH):
            batch = list(texts[start : start + VOYAGE_BATCH])
            data = voyage_post(
                "embeddings",
                {
                    "input": batch,
                    "model": self.model,
                    "input_type": input_type,
                    "output_dimension": self.dim,
                    "truncation": True,
                },
                base_url=self._base_url,
                timeout_s=self._timeout_s,
                client=self._client,
            )
            vectors.extend(_vectors(data, len(batch)))
            usage = data.get("usage") if isinstance(data, dict) else None
            if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
                self.total_tokens += usage["total_tokens"]
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]


def collection_model_name(provider: str, model: str, dim: int) -> str:
    """컬렉션에 기록하는 이름. 차원이 다르면 같은 모델이라도 다른 컬렉션이 필요하다."""
    return f"{provider}:{model}:{dim}"
