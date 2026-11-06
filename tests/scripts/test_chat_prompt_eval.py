"""실제 키/LLM/DB 없이 10요청·격리·복원·오류·Make 전달을 검증."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from weeing_weeing.agent.chat_usage import ChatCallUsage, ChatRunUsage
from weeing_weeing.agent.errors import LlmUsage
from weeing_weeing.contracts import ChatResponse

ROOT = Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location(
        "prompt_eval", ROOT / "scripts/run_chat_prompt_eval.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_default_and_make_are_free_plan_only(monkeypatch, capsys):
    m = module()
    monkeypatch.setattr(
        m.subprocess, "call", lambda *a, **k: pytest.fail("No subprocess in plan")
    )
    assert m.main([]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["total_service_requests"] == 10
    assert plan["repeats"] == 1 and len(plan["cases"]) == 5
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_chat_prompt_eval.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout)["mode"] == "plan_only_no_api_calls"


class Client:
    def __init__(self):
        self.closed = False

    def create(self, **kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name="search_knowledge")]
        )

    def close(self):
        self.closed = True


def harness(tmp_path, *, fail_at=None, raise_at=None):
    m = module()
    chat = SimpleNamespace(SYSTEM="new writing", CHAT_PROMPT_VERSION="chat-tools-v13")
    grounding = SimpleNamespace(
        SYSTEM="new review",
        CLARIFICATION_SYSTEM="new clarification",
        INSUFFICIENCY_SYSTEM="new insufficient",
    )
    modules = {"chat.py": chat, "chat_grounding.py": grounding}
    baseline = {
        "prompts": {
            "chat.py": {"SYSTEM": "old writing"},
            "chat_grounding.py": {
                "SYSTEM": "old review",
                "CLARIFICATION_SYSTEM": "old clarification",
                "INSUFFICIENCY_SYSTEM": "old insufficient",
            },
        }
    }
    calls, clients = [], []

    def factory():
        c = Client()
        clients.append(c)
        return c

    def service_factory(client):
        class Service:
            last_run = None

            def reply(self, question, *, context, timeout_s):
                assert not context.recent_turns
                calls.append(
                    (
                        chat.CHAT_PROMPT_VERSION,
                        chat.SYSTEM,
                        grounding.SYSTEM,
                        question.question,
                        question.request_id,
                    )
                )
                assert (chat.SYSTEM, grounding.SYSTEM) == (
                    ("old writing", "old review")
                    if chat.CHAT_PROMPT_VERSION == "chat-tools-v10"
                    else ("new writing", "new review")
                )
                if raise_at == len(calls):
                    raise RuntimeError("provider diagnostic must not escape")
                client.create()
                self.last_run = ChatRunUsage(
                    request_id=str(question.request_id),
                    calls=(
                        ChatCallUsage(
                            "dialogue", "fake", "fake", LlmUsage(10, 2, 12), 0.01, False
                        ),
                        ChatCallUsage("grounding", "fake", "fake", None, 0.01, False),
                    ),
                )
                if fail_at == len(calls):
                    return ChatResponse(
                        request_id=question.request_id,
                        applied_conditions=question.conditions,
                        intent="COMBINED",
                        status="FAILED",
                        message="실패",
                        failure={"code": "RATE_LIMITED", "retryable": True},
                        generated_at="2026-11-06T00:00:00Z",
                    )
                return ChatResponse(
                    request_id=question.request_id,
                    applied_conditions=question.conditions,
                    intent="OUT_OF_SCOPE",
                    status="OUT_OF_SCOPE",
                    message="자료 범위 확인",
                    generated_at="2026-11-06T00:00:00Z",
                )

        return Service()

    output = tmp_path / "results"
    return m, modules, baseline, factory, service_factory, calls, clients, output


def test_exactly_ten_requests_prompts_only_and_independent_contexts(tmp_path):
    m, modules, b, f, s, calls, clients, out = harness(tmp_path)
    rows = m.run_experiment({**m.load_plan(), "timeout_s": 30}, modules, b, f, s, out)
    assert len(rows) == len(calls) == 10
    assert len({c[-1] for c in calls}) == 10
    assert [c[0] for c in calls[:4]] == [
        "chat-tools-v10",
        "chat-tools-v13",
        "chat-tools-v13",
        "chat-tools-v10",
    ]
    assert modules["chat.py"].SYSTEM == "new writing"
    assert modules["chat_grounding.py"].SYSTEM == "new review"
    assert all(c.closed for c in clients)
    assert rows[0]["tool_turns"] == 1 and rows[0]["review_calls"] == 1
    assert rows[0]["tokens"] is None  # unknown is not zero
    summary = json.loads((out / "summary.json").read_text())
    assert summary["complete"] and summary["same_status_nonfailed_pairs"] == 5
    assert summary["variants"]["baseline"]["llm_calls"] == 10
    assert all(
        r["factual_accuracy_0_2"] is None
        for r in json.loads((out / "quality_review.json").read_text())
    )
    with pytest.raises(FileExistsError):
        m.run_experiment({**m.load_plan(), "timeout_s": 30}, modules, b, f, s, out)


def test_auth_or_quota_failure_stops_and_keeps_partial_results(tmp_path):
    m, mods, b, f, s, calls, clients, out = harness(tmp_path, fail_at=2)
    rows = m.run_experiment({**m.load_plan(), "timeout_s": 30}, mods, b, f, s, out)
    assert len(rows) == 2 and all(c.closed for c in clients)
    summary = json.loads((out / "summary.json").read_text())
    assert not summary["complete"] and summary["same_status_nonfailed_pairs"] == 0
    assert not summary["pairs"][0]["same_status_nonfailed"]
    assert mods["chat.py"].CHAT_PROMPT_VERSION == "chat-tools-v13"


def test_exception_restores_prompts_and_closes_clients(tmp_path):
    m, mods, b, f, s, calls, clients, out = harness(tmp_path, raise_at=2)
    with pytest.raises(RuntimeError):
        m.run_experiment({**m.load_plan(), "timeout_s": 30}, mods, b, f, s, out)
    assert len((out / "results.jsonl").read_text().splitlines()) == 1
    assert mods["chat.py"].SYSTEM == "new writing" and all(c.closed for c in clients)
    assert (out / "summary.json").exists()


def test_make_command_does_not_load_env():
    output = subprocess.run(
        ["make", "-n", "chat-prompt-eval", "ARGS=--execute --ask-key --ask-voyage-key"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout
    assert "--no-env-file" in output and "--env-file .env" not in output
    assert "scripts/run_chat_prompt_eval.py" in output


@pytest.mark.parametrize("backend", ["aws-local", "app"])
def test_worker_assembly_without_real_keys_or_services(
    tmp_path, monkeypatch, capsys, backend
):
    import weeing_weeing.agent.interface as agent
    import weeing_weeing.api.chat_knowledge as api
    import weeing_weeing.config as config
    import weeing_weeing.rag.interface as rag

    m, mods, baseline, factory, service, calls, clients, out = harness(tmp_path)
    snapshot = tmp_path / "replica.json"
    snapshot.write_text("{}")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))
    monkeypatch.setattr(m, "BASELINE_PATH", baseline_path)
    monkeypatch.setattr(
        m,
        "importlib",
        SimpleNamespace(
            import_module=lambda name: mods[name.rsplit(".", 1)[1] + ".py"]
        ),
    )
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            search_replica_path=str(snapshot),
            qdrant_url="http://127.0.0.1:16335",
            llm_timeout_s=30,
        ),
    )
    monkeypatch.setattr(agent, "get_llm_client", lambda **kwargs: factory())
    monkeypatch.setattr(
        api,
        "get_chat_knowledge",
        lambda: SimpleNamespace(
            retriever=object(),
            documents=SimpleNamespace(listed=lambda: []),
            reports=SimpleNamespace(approved_reports=lambda: []),
        ),
    )
    monkeypatch.setattr(
        api, "build_chat_service", lambda *, client, knowledge: service(client)
    )
    monkeypatch.setattr(rag, "close_rag_resources", lambda: None)
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(m.getpass, "getpass", lambda _: "fake-private-value")
    args = SimpleNamespace(ask_key=True, output=out, backend=backend)
    assert m.execute_worker(args, m.load_plan()) == 0
    assert len(calls) == 10 and all(c.closed for c in clients)
    metadata = json.loads((out / "metadata.json").read_text())
    assert metadata["snapshot_unchanged"]
    # Source paths outside ROOT can occur only in this injected test baseline path.
    assert "fake-private-value" not in capsys.readouterr().out
    assert "fake-private-value" not in "".join(p.read_text() for p in out.iterdir())
