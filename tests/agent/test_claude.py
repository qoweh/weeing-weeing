"""Claude 클라이언트: 스키마 변환, 요청 모양, 실패 → LlmError 변환. 실제 API는 부르지 않는다."""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from weeing_weeing.agent.claude import FALLBACK_BETA, ClaudeClient, strict_schema
from weeing_weeing.agent.interface import (
    LlmError,
    LlmModelMissingError,
    LlmRefusedError,
    LlmTimeoutError,
    LlmUnavailableError,
)
from weeing_weeing.agent.llm_check import AnalysisDraft

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def message(*blocks, stop_reason="end_turn", usage=(10, 5)):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
    )


def text(value):
    return SimpleNamespace(type="text", text=value)


class FakeSdk:
    """anthropic.Anthropic 대역. with_options(...).beta.messages.create만 흉내 낸다."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.options = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def with_options(self, **options):
        self.options.append(options)
        return self

    def _create(self, **params):
        self.calls.append(params)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def status_error(cls, code):
    response = httpx2.Response(code, request=REQUEST)
    return cls("error", response=response, body=None)


def test_strict_schema_closes_objects_and_drops_unsupported_keywords():
    schema = strict_schema(AnalysisDraft.model_json_schema())
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])  # 기본값 있는 칸도 required
    cause = schema["$defs"]["CauseCandidate"]
    assert cause["additionalProperties"] is False
    assert "default" not in json.dumps(schema)
    assert strict_schema({"type": "array", "minItems": 1, "items": {}}) == {
        "type": "array",
        "items": {},
    }


def test_generate_json_sends_schema_effort_and_fallback():
    sdk = FakeSdk(message(text('{"a": 1}')))
    client = ClaudeClient("claude-test", effort="low", sdk=sdk)
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}

    assert client.generate_json("sys", "user", timeout_s=7, schema=schema) == '{"a": 1}'
    call = sdk.calls[0]
    assert call["model"] == "claude-test"
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert len(sdk.options) == 1
    assert 0 < sdk.options[0]["timeout"] <= 7
    assert sdk.options[0]["max_retries"] == 0
    assert client.last_usage.input_tokens == 10
    assert client.last_usage.output_tokens == 5


def test_create_returns_response_for_tool_loop():
    reply = message(text("x"), stop_reason="tool_use")
    sdk = FakeSdk(reply)
    client = ClaudeClient("claude-test", sdk=sdk)
    got = client.create(system="s", messages=[], tools=[{"name": "t"}], timeout_s=5)
    assert got is reply
    assert sdk.calls[0]["tools"] == [{"name": "t"}]
    assert "format" not in sdk.calls[0]["output_config"]


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (anthropic.APITimeoutError(request=REQUEST), LlmTimeoutError),
        (anthropic.APIConnectionError(request=REQUEST), LlmUnavailableError),
        (status_error(anthropic.AuthenticationError, 401), LlmUnavailableError),
        (status_error(anthropic.NotFoundError, 404), LlmModelMissingError),
        (status_error(anthropic.InternalServerError, 500), LlmError),
        (message(text("no"), stop_reason="refusal"), LlmRefusedError),
        (message(text("{"), stop_reason="max_tokens"), LlmError),
        (message(text("  ")), LlmError),  # 빈 응답
        # 키·프로필이 없을 때 SDK가 요청 직전에 내는 오류
        (TypeError('"Could not resolve authentication method."'), LlmUnavailableError),
    ],
)
def test_failures_become_llm_errors(reply, error):
    client = ClaudeClient("claude-test", sdk=FakeSdk(reply))
    with pytest.raises(error):
        client.generate_json("s", "u", timeout_s=5)


def test_empty_model_is_rejected():
    with pytest.raises(ValueError):
        ClaudeClient("")


def test_unrelated_type_error_is_not_hidden():
    client = ClaudeClient("claude-test", sdk=FakeSdk(TypeError("bad argument")))
    with pytest.raises(TypeError):
        client.generate_json("s", "u", timeout_s=5)


def test_actual_response_model_and_usage_are_captured():
    response = message(text('{"ok":true}'))
    response.model = "actual-model-version"
    response.usage.cache_read_input_tokens = 12
    response.usage.cache_creation_input_tokens = 4
    client = ClaudeClient("requested-model", sdk=FakeSdk(response))
    client.generate_json("s", "u", timeout_s=5)
    assert client.last_response_model == "actual-model-version"
    assert client.last_usage.cache_read_input_tokens == 12
    assert client.last_usage.cache_creation_input_tokens == 4


@pytest.mark.parametrize("code,attempts", [(400, 1), (401, 1), (429, 3), (500, 3)])
def test_retry_policy_is_bounded_and_does_not_retry_auth_or_input(
    monkeypatch, code, attempts
):
    from weeing_weeing.agent import claude

    waits = []
    monkeypatch.setattr(claude.time, "sleep", waits.append)
    cls = anthropic.AuthenticationError if code == 401 else anthropic.APIStatusError
    sdk = FakeSdk(status_error(cls, code))
    with pytest.raises(LlmError):
        ClaudeClient("test", sdk=sdk).create(
            system="s", messages=[], tools=[], timeout_s=5
        )
    assert len(sdk.calls) == attempts
    assert waits == ([0.25, 0.5] if attempts == 3 else [])
    assert all(option["max_retries"] == 0 for option in sdk.options)


def test_missing_usage_and_failed_call_do_not_reuse_previous_tokens(monkeypatch):
    from weeing_weeing.agent import claude

    monkeypatch.setattr(claude.time, "sleep", lambda _: None)
    sdk = FakeSdk(message(text("{}")))
    client = ClaudeClient("test", sdk=sdk)
    client.generate_json("s", "u", timeout_s=5)
    assert client.last_usage.input_tokens == 10
    sdk.reply = status_error(anthropic.AuthenticationError, 401)
    with pytest.raises(LlmError):
        client.generate_json("s", "u", timeout_s=5)
    assert client.last_usage is None
    sdk.reply = message(text("{}"))
    sdk.reply.usage = None
    client.generate_json("s", "u", timeout_s=5)
    assert client.last_usage is None


def test_retry_does_not_start_when_remaining_budget_cannot_cover_backoff(monkeypatch):
    from weeing_weeing.agent import claude

    clock = [10.0]
    monkeypatch.setattr(claude.time, "monotonic", lambda: clock[0])
    sdk = FakeSdk(status_error(anthropic.APIStatusError, 429))
    original = sdk._create

    def slow(**params):
        clock[0] += 4.95
        return original(**params)

    sdk.beta.messages.create = slow
    with pytest.raises(LlmTimeoutError):
        ClaudeClient("test", sdk=sdk).create(
            system="s", messages=[], tools=[], timeout_s=5
        )
    assert len(sdk.calls) == 1


def test_explicit_key_is_passed_only_to_sdk_not_request_or_repr(monkeypatch):
    from weeing_weeing.agent import claude

    sdk = FakeSdk(message(text("{}")))
    received = []

    def factory(**kwargs):
        received.append(kwargs)
        return sdk

    monkeypatch.setattr(claude.anthropic, "Anthropic", factory)
    client = ClaudeClient("test", api_key="FAKE_SECRET_KEY_SENTINEL")
    client.generate_json("s", "u", timeout_s=5)
    assert received == [{"api_key": "FAKE_SECRET_KEY_SENTINEL"}]
    assert "FAKE_SECRET_KEY_SENTINEL" not in repr(client) + json.dumps(sdk.calls)
