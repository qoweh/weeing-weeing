"""실제 임베딩 모델 스모크 테스트. 모델 다운로드(수 GB)가 필요해 기본으로는 건너뛴다.

RAG_SLOW_TESTS=1 EMBEDDING_MODEL=BAAI/bge-m3 uv run --no-sync pytest tests/rag/test_real_model_smoke.py
"""

import dataclasses
import os

import pytest

from weeing_weeing.config import get_settings
from weeing_weeing.rag.factory import build_store
from weeing_weeing.rag.store import Chunk

pytestmark = pytest.mark.skipif(
    os.environ.get("RAG_SLOW_TESTS") != "1", reason="RAG_SLOW_TESTS=1일 때만 실행"
)

TEXTS = [
    "BTT2-P01 이송시간 초과: 입구에서 출구까지 트레이 이동 시간이 기준을 넘으면 벨트 슬립과 걸림을 점검한다.",
    "BTT2-P03 입구 장기 점유: 입구 광전센서가 오래 차단되면 트레이 걸림과 렌즈 오염을 확인한다.",
    "BTT2-M12 DE 진동 RMS 상한: 구동측 베어링 진동이 커지면 체결 상태와 윤활을 점검한다.",
]


@pytest.fixture(scope="module", params=["qdrant", "chroma"])
def store(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp(request.param)
    settings = dataclasses.replace(
        get_settings(),
        embedding_model=os.environ.get("EMBEDDING_MODEL") or "BAAI/bge-m3",
        vector_store=request.param,
        qdrant_path=tmp / "qdrant",
        qdrant_url="",
        chroma_dir=tmp / "chroma",
    )
    store = build_store(settings)
    store.replace_document(
        "BTT-MANUAL",
        [
            Chunk(
                f"BTT-MANUAL:2.0:{i:04d}",
                "BTT-MANUAL",
                "2.0",
                t,
                {"doc_type": "manual"},
            )
            for i, t in enumerate(TEXTS)
        ],
    )
    yield store
    store.close()


def test_dense_query_finds_meaning(store):
    hits = store.query("트레이가 입구 센서 앞에서 멈춰 있다", k=1)
    assert hits[0].chunk.chunk_id == "BTT-MANUAL:2.0:0001"


def test_hybrid_query_finds_code(store):
    hits = store.hybrid_query("M12 베어링", k=1)
    assert hits[0].chunk.chunk_id == "BTT-MANUAL:2.0:0002"
