"""챗봇 지연 기준선(#215): 질문 세트 로드, 질문별 측정·요약·보고서. 실제 LLM은 부르지 않는다."""

import json
from datetime import UTC, datetime

import pytest

from weeing_weeing.agent.chat_usage import ChatCallUsage, ChatRunUsage
from weeing_weeing.agent.errors import LlmUsage
from weeing_weeing.agent.interface import (
    format_latency_report,
    load_latency_cases,
    run_latency_baseline,
)
from weeing_weeing.config import PROJECT_ROOT
from weeing_weeing.contracts import ChatResponse


def call(purpose, seconds, usage=True):
    return ChatCallUsage(
        purpose=purpose,
        provider="fake",
        model="fake",
        usage=LlmUsage(100, 10, seconds, cache_read_input_tokens=80) if usage else None,
        elapsed_s=seconds,
        failed=False,
    )


class FakeService:
    def __init__(self, calls, status="INSUFFICIENT_EVIDENCE"):
        self.calls, self.status, self.last_run = calls, status, None

    def reply(self, question, *, context, timeout_s):
        self.last_run = ChatRunUsage(
            request_id=str(question.request_id),
            calls=tuple(self.calls),
            tool_names=("search_knowledge", "submit_answer"),
        )
        failed = self.status == "FAILED"
        return ChatResponse(
            request_id=question.request_id,
            intent="COMBINED",
            status=self.status,
            applied_conditions=question.conditions,
            message="안내",
            failure={"code": "TIMEOUT", "retryable": True} if failed else None,
            generated_at=datetime.now(UTC),
        )


def test_bundled_question_set_loads_with_unique_ids():
    cases = load_latency_cases(PROJECT_ROOT / "data/eval/chat_latency_v1.toml")
    assert len(cases) == 10
    assert len({c.case_id for c in cases}) == 10
    assert {"MANUAL", "HISTORY", "COMBINED", "INCIDENT", "OUT_OF_SCOPE"} <= {
        c.kind for c in cases
    }


def test_duplicate_ids_are_rejected(tmp_path):
    path = tmp_path / "cases.toml"
    path.write_text(
        'schema_version = 1\n[[cases]]\nid="A"\nkind="MANUAL"\nquestion="q"\n'
        '[[cases]]\nid="A"\nkind="MANUAL"\nquestion="q"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_latency_cases(path)


def test_rows_split_time_by_purpose_and_report_re_reviews(tmp_path):
    cases = load_latency_cases(PROJECT_ROOT / "data/eval/chat_latency_v1.toml")[:2]
    services = iter(
        [
            FakeService(
                [call("dialogue", 0.0), call("dialogue", 0.0), call("grounding", 0.0)]
            ),
            FakeService(
                [
                    call("dialogue", 0.0),
                    call("grounding", 0.0),
                    call("grounding", 0.0, usage=False),
                ],
                status="FAILED",
            ),
        ]
    )
    rows = run_latency_baseline(lambda: next(services), cases, timeout_s=5)
    first, second = rows
    assert (first.llm_calls, first.dialogue_calls, first.grounding_calls) == (3, 2, 1)
    assert first.input_tokens == 300 and first.cache_read_tokens == 240
    assert first.tools == ["search_knowledge", "submit_answer"]
    assert second.status == "FAILED" and second.failure_code == "TIMEOUT"
    assert second.input_tokens is None  # 사용량을 모르는 호출이 있으면 합계도 미확인

    report = format_latency_report(rows, title="테스트", settings={"모드": "fake"})
    assert "근거 재검토 발생 1건" in report
    assert "FAILED(TIMEOUT)" in report and "미확인" in report
    assert cases[0].question not in report  # 질문 본문을 남기지 않는다


def load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "chat_baseline", PROJECT_ROOT / "scripts/chat_baseline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_mode_only_prints_plan(monkeypatch, capsys):
    module = load_script()
    monkeypatch.setattr(
        module, "run_latency_baseline", lambda *a, **k: pytest.fail("실행하면 안 됨")
    )
    assert module.main([]) == 0
    assert "--execute(유료)" in capsys.readouterr().out


def test_replay_mode_writes_report_without_paid_calls(monkeypatch, tmp_path, capsys):
    module = load_script()
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    assert module.main(["--replay", "--only", "L01,L02", "--out", str(tmp_path)]) == 0
    [md] = tmp_path.glob("*.md")
    [js] = tmp_path.glob("*.json")
    assert "replay-no-cost" in md.read_text(encoding="utf-8")
    assert [row["case_id"] for row in json.loads(js.read_text())] == ["L01", "L02"]


def test_execute_asks_before_paid_run(monkeypatch, tmp_path):
    module = load_script()
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    monkeypatch.setattr(
        module, "run_latency_baseline", lambda *a, **k: pytest.fail("확인 없이 실행")
    )
    assert module.main(["--execute", "--out", str(tmp_path)]) == 1
