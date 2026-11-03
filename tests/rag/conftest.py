"""rag 테스트 fixture. 저장소 백엔드는 BACKENDS에 추가하면 계약 테스트가 같이 돈다.

Qdrant 서버 모드는 QDRANT_URL이 있을 때만 돈다.
    docker compose --profile qdrant up -d qdrant
    QDRANT_URL=http://localhost:6333 uv run --no-sync pytest tests/rag
"""

import os
import uuid
from contextlib import contextmanager

import chromadb
import pytest
from chromadb.config import Settings
from fakes import FakeEmbedder, MemoryVectorStore
from qdrant_client import QdrantClient

from weeing_weeing.rag.chroma_store import ChromaVectorStore
from weeing_weeing.rag.qdrant_store import QdrantVectorStore
from weeing_weeing.rag.sparse import KiwiBm25Encoder

MODEL = "fake-embedder-v1"
SPARSE = KiwiBm25Encoder()
_DEFAULT = object()


def _kwargs(kwargs: dict) -> dict:
    """make()에 sparse_encoder를 주지 않으면 Kiwi BM25를 쓴다. None이면 dense 전용."""
    sparse = kwargs.pop("sparse_encoder", _DEFAULT)
    return {**kwargs, "sparse_encoder": SPARSE if sparse is _DEFAULT else sparse}


@contextmanager
def _memory(tmp_path):
    storage: dict = {}

    def make(*, embedder=None, embedding_model=MODEL, **kwargs):
        return MemoryVectorStore(
            storage,
            embedder=embedder or FakeEmbedder(),
            embedding_model=embedding_model,
            **_kwargs(kwargs),
        )

    yield make


@contextmanager
def _qdrant(client: QdrantClient, collection: str = "knowledge"):
    """같은 client로 저장소를 다시 만들면 '같은 DB를 다시 연 것'이 된다."""

    def make(*, embedder=None, embedding_model=MODEL, **kwargs):
        return QdrantVectorStore(
            client,
            embedder=embedder or FakeEmbedder(),
            embedding_model=embedding_model,
            collection=collection,
            **_kwargs(kwargs),
        )

    try:
        yield make
    finally:
        if client.init_options.get("url"):
            client.delete_collection(collection)
        client.close()


def _qdrant_memory(tmp_path):
    return _qdrant(QdrantClient(":memory:"))


def _qdrant_path(tmp_path):
    return _qdrant(QdrantClient(path=str(tmp_path / "qdrant")))


def _qdrant_server(tmp_path):
    url = os.environ["QDRANT_URL"]
    return _qdrant(QdrantClient(url=url, timeout=10), f"test_{uuid.uuid4().hex[:12]}")


@contextmanager
def _chroma(tmp_path):
    # EphemeralClient는 프로세스 안에서 상태를 공유하므로 테스트마다 새 폴더를 쓴다.
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma"), settings=Settings(anonymized_telemetry=False)
    )

    def make(*, embedder=None, embedding_model=MODEL, **kwargs):
        return ChromaVectorStore(
            client,
            embedder=embedder or FakeEmbedder(),
            embedding_model=embedding_model,
            **_kwargs(kwargs),
        )

    yield make


# 이름 → (tmp_path → 같은 저장소를 다시 여는 함수를 내주는 context manager)
BACKENDS = {
    "memory": _memory,
    "qdrant-memory": _qdrant_memory,
    "qdrant-path": _qdrant_path,
    "chroma": _chroma,
}
if os.environ.get("QDRANT_URL"):
    BACKENDS["qdrant-server"] = _qdrant_server


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture(params=sorted(BACKENDS))
def store_factory(request, tmp_path):
    """같은 저장소를 다시 열 수 있는 함수. make(embedder=, embedding_model=, ...)."""
    with BACKENDS[request.param](tmp_path) as make:
        yield make


@pytest.fixture
def store(store_factory):
    return store_factory()
