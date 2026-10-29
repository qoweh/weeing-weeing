"""사용량 기록(#113): 무엇을 어떤 모양으로 남기는지, 기록이 실패해도 분석은 계속되는지.

실제 Langfuse 서버는 부르지 않는다. SDK 클라이언트와 propagate_attributes를 가짜로 바꾼다.
"""

import dataclasses
import logging
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from weeing_weeing.agent.claude import ClaudeClient
from weeing_weeing.agent.interface import LlmTimeoutError, get_llm_client
from weeing_weeing.agent.runtime import AgentSpec, FinishTool, run_agent
from weeing_weeing.agent.tracing import (
    NULL_TRACER,
    LangfuseTracer,
    build_tracer,
)
from weeing_weeing.config import get_settings


class FakeObservation:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.updates = {}

    def update(self, **fields):
        self.updates.update(fields)


class FakeLangfuse:
    """Langfuse 클라이언트 대역. 열린 기록과 묶음 속성(propagate)을 순서대로 쌓는다."""

    def __init__(self, fail_start=False):
        self.observations = []
        self.propagated = []
        self.flushed = 0
        self.fail_start = fail_start

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        if self.fail_start:
            raise RuntimeError("langfuse down")
        obs = FakeObservation(kwargs)
        self.observations.append(obs)
        yield obs

    @contextmanager
    def propagate(self, **kwargs):
        self.propagated.append(kwargs)
        yield

    def flush(self):
        self.flushed += 1


def tracer(fake, *, capture=False):
    return LangfuseTracer(
        fake,
        user_id="Gilssom",
        entrypoint="analyze",
        capture_content=capture,
        propagate=fake.propagate,
    )


def message(*blocks, stop_reason="end_turn", model="claude-test"):
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        cache_read_input_tokens=50,
        cache_creation_input_tokens=None,
    )
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop_reason, usage=usage, model=model
    )


class FakeSdk:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def with_options(self, **_):
        return self

    def _create(self, **_):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(name, data, id="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=data, id=id)


def test_claude_call_is_one_generation_with_token_usage():
    fake = FakeLangfuse()
    sdk = FakeSdk(message(text('{"a": 1}'), model="claude-fallback"))
    client = ClaudeClient("claude-test", sdk=sdk, tracer=tracer(fake))

    client.generate_json("s", "secret prompt", timeout_s=5)

    [gen] = fake.observations
    assert gen.kwargs["as_type"] == "generation"
    assert gen.kwargs["model"] == "claude-test"
    assert gen.kwargs["input"] is None  # 본문은 기본으로 보내지 않는다
    assert "output" not in gen.updates
    assert gen.updates["usage_details"] == {
        "input": 100,
        "output": 20,
        "cache_read_input_tokens": 50,
        "cache_creation_input_tokens": 0,
    }
    assert gen.updates["model"] == "claude-fallback"  # 실제로 답한 모델로 단가 계산
    # 바깥 기록이 없으면 이 호출이 trace가 되어 사람·기능 태그를 단다
    assert fake.propagated == [
        {
            "user_id": "Gilssom",
            "session_id": None,
            "tags": ["analyze"],
            "trace_name": "claude",
        }
    ]


def test_content_is_sent_only_when_enabled():
    fake = FakeLangfuse()
    sdk = FakeSdk(message(text('{"a": 1}')))
    client = ClaudeClient("claude-test", sdk=sdk, tracer=tracer(fake, capture=True))
    client.generate_json("s", "prompt", timeout_s=5)
    [gen] = fake.observations
    assert gen.kwargs["input"] == [{"role": "user", "content": "prompt"}]
    assert gen.updates["output"] == [{"type": "text", "text": '{"a": 1}'}]


def test_failed_call_is_recorded_as_error_and_still_raises():
    import anthropic
    import httpx2

    fake = FakeLangfuse()
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    sdk = FakeSdk(anthropic.APITimeoutError(request=request))
    client = ClaudeClient("claude-test", sdk=sdk, tracer=tracer(fake))
    with pytest.raises(LlmTimeoutError):
        client.generate_json("s", "u", timeout_s=5)
    [gen] = fake.observations
    assert gen.updates["level"] == "ERROR"
    assert "LlmTimeoutError" in gen.updates["status_message"]


def test_agent_run_is_one_trace_with_session_and_nested_calls():
    fake = FakeLangfuse()
    sdk = FakeSdk(
        message(tool_use("lookup", {"q": "x"}), stop_reason="tool_use"),
        message(tool_use("submit", {"answer": "ok"}, id="t2"), stop_reason="tool_use"),
    )
    client = ClaudeClient("claude-test", sdk=sdk, tracer=tracer(fake))
    from weeing_weeing.agent.runtime import AgentTool

    spec = AgentSpec(
        name="incident-analyst",
        system="s",
        tools=(AgentTool("lookup", "d", {"type": "object"}, lambda d, m: "found"),),
        finish=FinishTool("submit", "d", {"type": "object"}, lambda d, m: d["answer"]),
        prompt_version="v9",
    )
    output, _ = run_agent(client, spec, "task", timeout_s=5, session_id="INC-1")

    assert output == "ok"
    kinds = [(o.kwargs["as_type"], o.kwargs["name"]) for o in fake.observations]
    assert kinds == [
        ("agent", "incident-analyst"),
        ("generation", "claude"),
        ("tool", "lookup"),
        ("generation", "claude"),
        ("tool", "submit"),
    ]
    # 사람·사건·태그는 가장 바깥(에이전트 실행)에서 한 번만 붙인다
    assert fake.propagated == [
        {
            "user_id": "Gilssom",
            "session_id": "INC-1",
            "tags": ["analyze", "v9"],
            "trace_name": "incident-analyst",
        }
    ]
    assert fake.observations[0].updates["metadata"]["turns"] == 2


def test_tracing_failure_never_blocks_the_call(caplog):
    fake = FakeLangfuse(fail_start=True)
    sdk = FakeSdk(message(text('{"a": 1}')))
    client = ClaudeClient("claude-test", sdk=sdk, tracer=tracer(fake))
    with caplog.at_level(logging.WARNING):
        assert client.generate_json("s", "u", timeout_s=5) == '{"a": 1}'
    assert "Langfuse 기록 시작 실패" in caplog.text


def test_flush_errors_are_swallowed():
    class Broken(FakeLangfuse):
        def flush(self):
            raise ConnectionError("no route")

    tracer(Broken()).flush()  # 예외 없음


def test_build_tracer_is_off_without_url_or_keys(monkeypatch, caplog):
    settings = get_settings()
    off = dataclasses.replace(settings, langfuse_base_url="")
    assert build_tracer(off, entrypoint="x") is NULL_TRACER

    on = dataclasses.replace(settings, langfuse_base_url="https://lf.example.com")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    with caplog.at_level(logging.WARNING):
        assert build_tracer(on, entrypoint="x") is NULL_TRACER
    assert "LANGFUSE_PUBLIC_KEY" in caplog.text


def test_get_llm_client_has_null_tracer_by_default(monkeypatch):
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    client = get_llm_client(entrypoint="test")
    assert client.tracer is NULL_TRACER
