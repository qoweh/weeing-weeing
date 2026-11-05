"""무과금 Langfuse 기록 확인(#206): 실제 Claude·Voyage·Langfuse 없이 흐름과 기록 모양을 검증한다."""

import dataclasses
import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from weeing_weeing.agent.interface import (
    get_chat_service,
    get_replay_llm_client,
    replay_sample_knowledge,
)
from weeing_weeing.agent.tracing import LangfuseTracer
from weeing_weeing.config import get_settings
from weeing_weeing.contracts import ChatContext, ChatQuestion

SCRIPT = Path(__file__).parents[2] / "scripts" / "langfuse_smoke.py"


class FakeLangfuse:
    """Langfuse 클라이언트 대역. 서버로 보내지 않고 기록만 쌓는다."""

    def __init__(self):
        self.observations, self.scores = [], []

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        obs = SimpleNamespace(kwargs=kwargs, update=lambda **_: None)
        self.observations.append(obs)
        yield obs

    @contextmanager
    def propagate(self, **kwargs):
        yield

    def score_current_trace(self, **kwargs):
        self.scores.append(kwargs)

    def flush(self):
        pass


def tracer(fake):
    return LangfuseTracer(
        fake, user_id="test", entrypoint="trace-smoke", propagate=fake.propagate
    )


def load_script():
    spec = importlib.util.spec_from_file_location("langfuse_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ask(question):
    settings = get_settings()
    client = get_replay_llm_client(settings)
    fake = FakeLangfuse()
    client.tracer = tracer(fake)
    service = get_chat_service(
        replay_sample_knowledge(), client=client, settings=settings
    )
    response = service.reply(
        ChatQuestion(request_id=uuid4(), question=question),
        context=ChatContext(),
        timeout_s=10,
    )
    return response, fake, client


def test_replay_answers_from_sample_and_records_real_generation_shape():
    response, fake, client = ask("입구 센서 점검 방법")
    assert response.status == "OK"
    assert response.sources[0].doc_id == "SMOKE-MAN-1"
    generations = [
        o.kwargs["name"]
        for o in fake.observations
        if o.kwargs["as_type"] == "generation"
    ]
    assert generations == [
        "chat-assistant.turn-1",
        "chat-assistant.turn-2",
        "grounding-review.answer",
    ]
    assert client._sdk.calls == 3  # 재생 SDK만 불렀다
    assert {s["name"] for s in fake.scores} >= {"chat.status", "chat.llm_calls"}


def test_replay_without_matching_sample_reports_insufficient_evidence():
    response, fake, _ = ask("zzz")
    assert response.status == "INSUFFICIENT_EVIDENCE"
    assert any(
        o.kwargs["name"] == "grounding-review.insufficiency" for o in fake.observations
    )


def test_script_runs_without_langfuse_settings(monkeypatch, capsys):
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    module = load_script()
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: dataclasses.replace(get_settings(), langfuse_base_url=""),
    )
    assert module.main(["입구 센서 점검"]) == 0
    out = capsys.readouterr().out
    assert "status=OK" in out and "environment=test" in out
    assert "기록하지 않았다" in out


def test_real_knowledge_refuses_paid_search_settings(monkeypatch, capsys):
    module = load_script()
    paid = dataclasses.replace(get_settings(), embedding_provider="voyage")
    monkeypatch.setattr(module, "get_settings", lambda: paid)
    assert module.main(["--real-knowledge"]) == 2
    assert "hashing" in capsys.readouterr().err


def test_script_tells_where_to_find_the_trace(monkeypatch, capsys):
    module = load_script()
    fake = FakeLangfuse()
    real = module.get_replay_llm_client

    def client(settings):
        built = real(settings)
        built.tracer = tracer(fake)
        return built

    monkeypatch.setattr(module, "get_replay_llm_client", client)
    assert module.main(["입구 센서 점검", "--session", "smoke-1"]) == 0
    out = capsys.readouterr().out
    assert "세션 smoke-1" in out and "metadata.run_id" in out
    assert "셸에 export된 LANGFUSE_*" in out
