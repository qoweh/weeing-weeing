"""Ollama 네이티브 클라이언트: 요청 모양, 응답 처리, 실패를 LlmError로 알리기. 서버 없이 가짜 전송으로."""

import json

import httpx
import pytest

from weeing_weeing.agent.interface import (
    LlmClient,
    LlmError,
    LlmModelMissingError,
    LlmTimeoutError,
    LlmUnavailableError,
    get_llm_client,
)
from weeing_weeing.agent.ollama import OllamaClient

OK_BODY = {
    "message": {"role": "assistant", "content": '{"city": "서울"}'},
    "prompt_eval_count": 41,
    "eval_count": 24,
    "total_duration": 2_000_000_000,
    "load_duration": 500_000_000,
    "eval_duration": 1_000_000_000,
}


def client_with(handler, **kwargs) -> OllamaClient:
    return OllamaClient(
        "http://ollama:11434/",
        "qwen3:8b",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_request_uses_native_chat_with_schema_and_options():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    schema = {"type": "object", "properties": {"city": {"type": "string"}}}
    client: LlmClient = client_with(handler, keep_alive="1h")
    text = client.generate_json("시스템", "질문", timeout_s=5, schema=schema)

    assert text == '{"city": "서울"}'
    assert seen["url"] == "http://ollama:11434/api/chat"
    body = seen["body"]
    assert body["model"] == "qwen3:8b"
    assert body["messages"] == [
        {"role": "system", "content": "시스템"},
        {"role": "user", "content": "질문"},
    ]
    assert body["format"] == schema
    assert body["stream"] is False
    assert body["think"] is False  # 기본은 생각 단계 끔
    assert body["keep_alive"] == "1h"
    assert body["options"]["temperature"] == 0


def test_without_schema_asks_for_any_json():
    def handler(request):
        assert json.loads(request.content)["format"] == "json"
        return httpx.Response(200, json=OK_BODY)

    client_with(handler).generate_json("s", "u", timeout_s=5)


def test_usage_is_recorded():
    client = client_with(lambda r: httpx.Response(200, json=OK_BODY))
    client.generate_json("s", "u", timeout_s=5)
    usage = client.last_usage
    assert (usage.prompt_tokens, usage.output_tokens) == (41, 24)
    assert (usage.total_s, usage.load_s, usage.eval_s) == (2.0, 0.5, 1.0)
    assert usage.tokens_per_s == 24.0  # 생성 구간만으로 계산(프롬프트·로딩 제외)


def test_think_and_options_can_be_set():
    def handler(request):
        body = json.loads(request.content)
        assert body["think"] is True
        assert body["options"] == {"temperature": 0.3, "num_ctx": 8192}
        return httpx.Response(200, json=OK_BODY)

    client_with(
        handler, think=True, options={"temperature": 0.3, "num_ctx": 8192}
    ).generate_json("s", "u", timeout_s=5)


def test_timeout_is_llm_timeout_error():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LlmTimeoutError, match="5초"):
        client_with(handler).generate_json("s", "u", timeout_s=5)


def test_connection_failure_is_unavailable_with_hint():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LlmUnavailableError, match="Ollama"):
        client_with(handler).generate_json("s", "u", timeout_s=5)


def test_missing_model_tells_how_to_pull():
    client = client_with(
        lambda r: httpx.Response(404, json={"error": "model 'qwen3:8b' not found"})
    )
    with pytest.raises(LlmModelMissingError, match="ollama pull qwen3:8b"):
        client.generate_json("s", "u", timeout_s=5)


def test_other_404_is_not_reported_as_missing_model():
    """주소가 Ollama가 아닌 곳(프록시 등)을 가리켜도 ollama pull을 안내하지 않는다."""
    client = client_with(lambda r: httpx.Response(404, text="<html>Not Found</html>"))
    with pytest.raises(LlmError) as info:
        client.generate_json("s", "u", timeout_s=5)
    assert not isinstance(info.value, LlmModelMissingError)
    assert "HTTP 404" in str(info.value)


@pytest.mark.parametrize(
    "error",
    [
        lambda r: httpx.RemoteProtocolError("closed", request=r),
        lambda r: httpx.DecodingError("bad gzip", request=r),
    ],
)
def test_other_request_errors_are_unavailable(error):
    def handler(request):
        raise error(request)

    with pytest.raises(LlmUnavailableError):
        client_with(handler).generate_json("s", "u", timeout_s=5)


def test_malformed_base_url_is_unavailable():
    client = OllamaClient("http://[bad", "qwen3:8b")
    with pytest.raises(LlmUnavailableError, match="OLLAMA_BASE_URL"):
        client.generate_json("s", "u", timeout_s=1)


@pytest.mark.parametrize(("value", "sent"), [("-1", -1), ("300", 300), ("5m", "5m")])
def test_keep_alive_number_is_sent_as_seconds(value, sent):
    def handler(request):
        assert json.loads(request.content)["keep_alive"] == sent
        return httpx.Response(200, json=OK_BODY)

    client_with(handler, keep_alive=value).generate_json("s", "u", timeout_s=5)


def test_missing_counters_do_not_crash():
    body = {"message": {"content": "{}"}, "total_duration": None}
    client = client_with(lambda r: httpx.Response(200, json=body))
    client.generate_json("s", "u", timeout_s=5)
    assert client.last_usage.tokens_per_s == 0.0


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(500, json={"error": "out of memory"}), "out of memory"),
        (httpx.Response(200, text="not json"), "JSON이 아니다"),
        (httpx.Response(200, json={"message": {"content": "  "}}), "빈 응답"),
        (httpx.Response(200, json=["not", "dict"]), "모양"),
        (httpx.Response(200, json={"message": "text"}), "빈 응답"),
    ],
)
def test_bad_responses_are_llm_errors(response, message):
    with pytest.raises(LlmError, match=message):
        client_with(lambda r: response).generate_json("s", "u", timeout_s=5)


def test_empty_model_is_rejected():
    with pytest.raises(ValueError, match="OLLAMA_MODEL"):
        OllamaClient("http://x", "")


def test_get_llm_client_reads_settings(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_THINK", "true")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "0")
    client = get_llm_client()
    assert client.model_name == "qwen3:8b"
    assert client._think is True and client._keep_alive == 0  # 숫자는 초
