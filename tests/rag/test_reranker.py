"""모델 다운로드 없이 관련도 정렬·출처 보존·추론 실패 처리를 검증한다."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from weeing_weeing.rag import reranker
from weeing_weeing.rag.reranker import CrossEncoderReranker
from weeing_weeing.rag.store import Chunk, Hit


def hits():
    return [
        Hit(Chunk(f"MAN:1:{i:04d}", "MAN", "1", text, {"citation": text}), score)
        for i, (text, score) in enumerate(
            [("속도 점검", 0.03), ("광전 센서 오염", 0.02), ("에너지 격리", 0.01)]
        )
    ]


def test_lazy_model_reused_and_rrf_scores_preserved(monkeypatch):
    model = Mock()
    model.predict.return_value = [-1.0, 5.0, 0.0]
    load = Mock(return_value=model)
    monkeypatch.setattr(reranker, "_load_model", load)
    ranker = CrossEncoderReranker("local-model", batch_size=2)
    candidates = hits()
    load.assert_not_called()

    for _ in range(2):
        found = ranker.rerank("센서 오염", candidates)
        assert found == [candidates[1], candidates[2], candidates[0]]
        assert found[0] is candidates[1]  # 원본 청크·RRF 점수·인용을 통째로 보존
    load.assert_called_once_with("local-model")
    model.predict.assert_called_with(
        [("센서 오염", hit.chunk.text) for hit in candidates],
        batch_size=2,
        show_progress_bar=False,
    )


def test_tied_scores_keep_hybrid_order(monkeypatch):
    model = Mock()
    model.predict.return_value = [0.0, 0.0, 0.0]
    monkeypatch.setattr(reranker, "_load_model", lambda _: model)
    candidates = hits()
    assert CrossEncoderReranker("local").rerank("질문", candidates) == candidates


def test_no_candidates_does_not_load_model(monkeypatch):
    load = Mock()
    monkeypatch.setattr(reranker, "_load_model", load)
    assert CrossEncoderReranker("local").rerank("질문", []) == []
    load.assert_not_called()


@pytest.mark.parametrize(
    "scores", [[0.1], [0.1, float("nan"), 0.2], [float("inf")] * 3]
)
def test_invalid_model_scores_are_rejected(monkeypatch, scores):
    model = Mock()
    model.predict.return_value = scores
    monkeypatch.setattr(reranker, "_load_model", lambda _: model)
    with pytest.raises(ValueError):
        CrossEncoderReranker("local").rerank("질문", hits())


def test_model_failure_is_not_no_evidence(monkeypatch):
    model = Mock()
    model.predict.side_effect = RuntimeError("추론 실패")
    monkeypatch.setattr(reranker, "_load_model", lambda _: model)
    with pytest.raises(RuntimeError, match="추론 실패"):
        CrossEncoderReranker("local").rerank("질문", hits())


def test_model_loading_is_local_only(monkeypatch):
    model = SimpleNamespace(num_labels=1)
    constructor = Mock(return_value=model)
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=constructor)
    )
    assert reranker._load_model("local") is model
    constructor.assert_called_once_with(
        "local", local_files_only=True, trust_remote_code=False
    )
    model.num_labels = 2
    with pytest.raises(ValueError, match="점수 하나"):
        reranker._load_model("classifier")


@pytest.mark.parametrize(
    "kwargs",
    [{"model_name": " "}, {"batch_size": 0}, {"batch_size": True}, {"batch_size": 1.5}],
)
def test_invalid_configuration(kwargs):
    with pytest.raises((ValueError, TypeError)):
        CrossEncoderReranker(**{"model_name": "local", **kwargs})
