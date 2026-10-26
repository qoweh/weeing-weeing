"""rag 테스트 fixture. 저장소 백엔드는 BACKENDS에 추가하면 계약 테스트가 같이 돈다."""

import pytest
from fakes import FakeEmbedder, MemoryVectorStore

MODEL = "fake-embedder-v1"


def _memory_factory(tmp_path):
    storage: dict = {}

    def make(*, embedder=None, embedding_model=MODEL, **kwargs):
        return MemoryVectorStore(
            storage,
            embedder=embedder or FakeEmbedder(),
            embedding_model=embedding_model,
            **kwargs,
        )

    return make


# 이름 → (tmp_path → 같은 저장소를 다시 여는 함수)
BACKENDS = {"memory": _memory_factory}


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture(params=sorted(BACKENDS))
def store_factory(request, tmp_path):
    """같은 저장소를 다시 열 수 있는 함수. make(embedder=, embedding_model=)."""
    return BACKENDS[request.param](tmp_path)


@pytest.fixture
def store(store_factory):
    return store_factory()
