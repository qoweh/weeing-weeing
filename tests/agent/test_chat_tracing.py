"""챗봇 기록(#202~#205): 조회 단계 span·근거 검토 이름·결과 점수.

Langfuse·Claude·검색 서버는 부르지 않는다. 기록기는 가짜 Langfuse 클라이언트를 쓴다.
"""

from uuid import uuid4

from test_chat_service import (
    CommonKnowledge,
    FakeClient,
    reply,
    search,
    submit,
)
from test_tracing import FakeLangfuse, FakeSdk, message, text, tracer

from weeing_weeing.agent.chat import ToolChatService
from weeing_weeing.agent.chat_grounding import verify_grounding
from weeing_weeing.agent.claude import ClaudeClient
from weeing_weeing.agent.interface import load_faq_catalog
from weeing_weeing.contracts import ChatContext, ChatQuestion


class Reviewing(FakeClient):
    def __init__(self, *responses, verdicts=()):
        super().__init__(*responses)
        self.verdicts = list(verdicts)

    def generate_json(self, system, user, **kwargs):
        if self.verdicts:
            return self.verdicts.pop(0)
        return super().generate_json(system, user, **kwargs)


def run(client, knowledge=None):
    fake = FakeLangfuse()
    client.tracer = tracer(fake)
    service = ToolChatService(
        client, knowledge or CommonKnowledge(), load_faq_catalog()
    )
    response = service.reply(
        ChatQuestion(request_id=uuid4(), question="입구 센서 점검"),
        context=ChatContext(),
        timeout_s=10,
    )
    return response, fake


def names(fake):
    return [(o.kwargs["as_type"], o.kwargs["name"]) for o in fake.observations]


def test_chat_question_is_one_trace_with_knowledge_spans_by_stage():
    response, fake = run(Reviewing(reply(search()), reply(submit())))
    assert response.status == "OK"
    assert names(fake)[:2] == [("chain", "chat"), ("agent", "chat-assistant")]
    assert [p["trace_name"] for p in fake.propagated] == ["chat"]
    assert "chat-tools-v7" in fake.propagated[0]["tags"]
    spans = [
        (o.kwargs["name"], o.updates["metadata"]["stage"])
        for o in fake.observations
        if o.kwargs["name"].startswith("knowledge.")
    ]
    assert spans == [
        ("knowledge.validate_query", "search_knowledge"),
        ("knowledge.search", "search_knowledge"),
        ("knowledge.is_searchable", "search_knowledge"),
        ("knowledge.is_searchable", "before_submit"),
        ("knowledge.is_searchable", "after_review"),
    ]
    search_span = next(
        o for o in fake.observations if o.kwargs["name"] == "knowledge.search"
    )
    assert search_span.kwargs["as_type"] == "retriever"
    assert search_span.updates["metadata"] == {
        "stage": "search_knowledge",
        "kind": "MANUAL",
        "returned": 1,
    }


def test_chat_scores_status_calls_and_each_grounding_verdict():
    unsupported = '{"verdict":"UNSUPPORTED","unsupported_parts":[0]}'
    client = Reviewing(
        reply(search()), reply(submit()), reply(submit()), verdicts=[unsupported]
    )
    response, fake = run(client)
    assert response.status == "OK"
    scores = [(s["name"], s["value"]) for s in fake.scores]
    assert scores == [
        ("chat.grounding_verdict", "UNSUPPORTED"),
        ("chat.grounding_verdict", "SUPPORTED"),
        ("chat.status", "OK"),
        ("chat.llm_calls", 5),  # 도구 루프 3번 + 근거 검토 2번
    ]
    assert fake.scores[1]["comment"] == "ANSWER #2"
    chat = fake.observations[0]
    assert chat.updates["metadata"]["llm_calls"] == 5
    assert chat.updates["metadata"]["tools"] == [
        "search_knowledge",
        "submit_answer",
        "submit_answer",
    ]


def test_search_failure_is_scored_as_failed_with_code():
    knowledge = CommonKnowledge(search_error=ConnectionError("FAKE_SECRET_SENTINEL"))
    response, fake = run(Reviewing(reply(search())), knowledge)
    assert response.status == "FAILED"
    scores = {s["name"]: s["value"] for s in fake.scores}
    assert scores["chat.status"] == "FAILED"
    assert scores["chat.failure_code"] == "SEARCH_UNAVAILABLE"
    assert "FAKE_SECRET_SENTINEL" not in repr(fake.scores)
    assert all("FAKE_SECRET_SENTINEL" not in repr(o.updates) for o in fake.observations)


def test_grounding_review_generation_is_named_by_mode():
    fake = FakeLangfuse()
    sdk = FakeSdk(message(text('{"verdict":"SUPPORTED","unsupported_parts":[]}')))
    client = ClaudeClient("claude-test", sdk=sdk, tracer=tracer(fake))
    verify_grounding(
        client, {"mode": "INSUFFICIENCY", "parts": [{"text": "x"}]}, timeout_s=5
    )
    [gen] = fake.observations
    assert gen.kwargs["name"] == "grounding-review.insufficiency"
    assert gen.updates["metadata"]["mode"] == "INSUFFICIENCY"
