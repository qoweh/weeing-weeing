import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "check_rag_agent", ROOT / "scripts/check_rag_agent.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_plan_is_one_question_and_does_not_create_client_or_storage(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        runner, "get_llm_client", lambda *a, **kw: pytest.fail("유료 호출 금지")
    )
    monkeypatch.setattr(
        runner.factory, "build_store", lambda *a, **kw: pytest.fail("색인 실행 금지")
    )
    output = tmp_path / "not-created"
    assert runner.main(["--out", str(output)]) == 0
    assert not output.exists()
    plan = capsys.readouterr().out
    assert '"max_application_calls": 6' in plan
    assert '"max_dialogue_turns": 4' in plan
    assert '"case": "o02"' in plan


def test_retriever_records_actual_hits_without_changing_search():
    hit = SimpleNamespace(chunk=SimpleNamespace(chunk_id="D:1:0"), relevance=0.4)
    calls = []

    def search_hits(query, **kwargs):
        calls.append((query, kwargs))
        return [hit]

    measured = runner.MeasuredRetriever(SimpleNamespace(search_hits=search_hits))
    measured.phase = "agent"
    assert measured.search_hits("질문", k=5, versions={"D": "1"}) == [hit]
    assert calls == [("질문", {"k": 5, "versions": {"D": "1"}})]
    assert measured.calls[0]["phase"] == "agent"
    assert measured.calls[0]["hits"] == [{"id": "D:1:0", "relevance": 0.4}]
