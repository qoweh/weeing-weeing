import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fakes import FakeEmbedder, MemoryVectorStore

from weeing_weeing.rag.sparse import KiwiBm25Encoder

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "check_rag_agent_integration", ROOT / "scripts/check_rag_agent.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_evaluation_uses_real_registry_and_agent_but_no_paid_client(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RERANKER_MODEL", "rerank-3-lite")  # 기본값은 리랭커 끔
    write = runner.write_json

    def checked_write(path, value):
        if path.name in {"failure.json", "cleanup_failure.json"}:
            raise AssertionError(value)
        write(path, value)

    monkeypatch.setattr(runner, "write_json", checked_write)
    monkeypatch.setattr(
        runner.factory, "_default_embedder", lambda name: FakeEmbedder()
    )
    monkeypatch.setattr(
        runner.factory,
        "build_store",
        lambda settings, *, embedder: MemoryVectorStore(
            {},
            embedder=embedder,
            embedding_model="fake",
            sparse_encoder=KiwiBm25Encoder(),
        ),
    )
    monkeypatch.setattr(
        runner.factory,
        "build_reranker",
        lambda *a, **kw: SimpleNamespace(
            rerank=lambda query, hits: [replace(h, relevance=0.4) for h in hits]
        ),
    )
    closed = []
    client = SimpleNamespace(
        provider="fake",
        model_name="fake",
        last_usage=None,
        last_attempts=1,
        create=lambda **kwargs: SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="finish",
                    name="submit_answer",
                    input={
                        "intent": "OUT_OF_SCOPE",
                        "status": "OUT_OF_SCOPE",
                        "message": "범위 밖",
                        "parts": [],
                        "clarification_questions": [],
                    },
                )
            ]
        ),
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(runner, "get_llm_client", lambda *a, **kw: client)
    output = tmp_path / "episode"
    assert runner.main(["--execute", "--out", str(output)]) == 0
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "OUT_OF_SCOPE"
    assert summary["preflight_count"] > 0
    assert summary["usage"]["tool_names"] == ["submit_answer"]
    assert summary["searches"][0]["phase"] == "preflight"
    assert closed == [True]
