"""#89: 실API 없이 근거 과장·충돌·검토 실패·사용량·출처 변경을 재현한다."""

import json
from contextlib import contextmanager
from uuid import uuid4

import pytest
from test_chat_service import CommonKnowledge, FakeClient, ask, reply, search, submit

from weeing_weeing.agent.chat import ToolChatService
from weeing_weeing.agent.interface import (
    LlmAuthenticationError,
    LlmInvalidResponseError,
    LlmRateLimitError,
    LlmServiceError,
    LlmTimeoutError,
    LlmUsage,
    load_faq_catalog,
)
from weeing_weeing.contracts import ChatContext, ChatQuestion


class ReviewingClient(FakeClient):
    def __init__(self, *responses, verdicts=None, known_usage=True):
        super().__init__(*responses)
        self.verdicts = iter(verdicts or ["SUPPORTED"])
        self.checks = []
        self.known_usage = known_usage
        self.last_response_model = "actual-test-model"

    def create(self, **kwargs):
        self.last_usage = None
        result = super().create(**kwargs)
        self.last_usage = LlmUsage(10, 2, 0.1) if self.known_usage else None
        return result

    def generate_json(self, system, user, **kwargs):
        self.last_usage = None
        self.checks.append(json.loads(user))
        value = next(self.verdicts)
        if isinstance(value, Exception):
            raise value
        self.last_usage = LlmUsage(10, 2, 0.1) if self.known_usage else None
        if value.startswith("RAW:"):
            return value[4:]
        return json.dumps(
            dict(verdict=value, unsupported_parts=[] if value == "SUPPORTED" else [0])
        )


def test_unsupported_claim_must_be_corrected_and_only_cited_body_is_reviewed():
    client = ReviewingClient(
        reply(search()),
        reply(submit(text="센서 오염이 확정되어 반드시 교체합니다.")),
        reply(submit(text="센서 상태를 확인합니다.")),
        verdicts=["UNSUPPORTED", "SUPPORTED"],
    )
    service = ToolChatService(client, CommonKnowledge(), load_faq_catalog())
    question = ChatQuestion(request_id=uuid4(), question="센서 점검 방법은?")
    response = service.reply(question, context=ChatContext(), timeout_s=10)
    assert response.status == "OK" and "교체" not in response.parts[0].text
    assert len(client.checks) == 2
    assert set(client.checks[0]["evidence"]) == {"manual:1"}
    assert client.checks[0]["evidence"]["manual:1"]["text"] == "센서 상태를 확인한다."
    usage = service.last_run
    assert len(usage.calls) == 5 and usage.total.input_tokens == 50
    assert [c.purpose for c in usage.calls].count("grounding") == 2
    assert all(c.model == "actual-test-model" for c in usage.calls)


def test_twice_unsupported_stops_with_insufficient_evidence():
    client = ReviewingClient(
        reply(search()),
        reply(submit()),
        reply(submit()),
        verdicts=["UNSUPPORTED", "UNSUPPORTED"],
    )
    response = ask(client)
    assert response.status == "INSUFFICIENT_EVIDENCE"
    assert not response.parts and not response.sources
    assert len(client.checks) == 2


def test_conflicting_evidence_asks_instead_of_combining_claims():
    response = ask(
        ReviewingClient(reply(search()), reply(submit()), verdicts=["CONFLICT"])
    )
    assert response.status == "NEEDS_CLARIFICATION"
    assert response.clarification_questions and not response.parts


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '{"verdict":"SUPPORTED","unsupported_parts":[0]}',
        '{"verdict":"UNSUPPORTED","unsupported_parts":[5]}',
    ],
)
def test_malformed_review_never_becomes_ok(raw):
    response = ask(
        ReviewingClient(reply(search()), reply(submit()), verdicts=["RAW:" + raw])
    )
    assert response.failure.code == "INVALID_RESPONSE"
    assert not response.parts and raw not in response.model_dump_json()


@pytest.mark.parametrize(
    "error,code,retryable",
    [
        (LlmAuthenticationError("safe auth error"), "LLM_AUTHENTICATION", False),
        (LlmRateLimitError(429), "RATE_LIMITED", True),
        (LlmServiceError("safe service error"), "LLM_SERVICE", True),
        (LlmTimeoutError("safe timeout"), "TIMEOUT", True),
        (LlmInvalidResponseError("safe format"), "INVALID_RESPONSE", False),
    ],
)
def test_provider_error_categories_are_preserved(error, code, retryable):
    for client in (
        ReviewingClient(error),
        ReviewingClient(reply(search()), reply(submit()), verdicts=[error]),
    ):
        response = ask(client)
        assert response.failure.code == code
        assert response.failure.retryable is retryable


def test_deleted_during_review_and_backend_failure_do_not_escape():
    class Knowledge(CommonKnowledge):
        def is_searchable(self, source, *, timeout_s):
            self.reads.append(source)
            if len(self.reads) > 2:
                raise RuntimeError("PRIVATE_BACKEND_SENTINEL")
            return True

    response = ask(ReviewingClient(reply(search()), reply(submit())), Knowledge())
    assert response.failure.code == "SEARCH_UNAVAILABLE"
    assert "PRIVATE_BACKEND_SENTINEL" not in response.model_dump_json()


def test_message_cannot_hide_an_unverified_claim():
    client = ReviewingClient(
        reply(search()), reply(submit(message="PRIVATE_UNSUPPORTED_CLAIM"))
    )
    response = ask(client)
    assert (
        response.status == "OK"
        and "PRIVATE_UNSUPPORTED_CLAIM" not in response.model_dump_json()
    )


def test_unknown_usage_is_none_and_statistics_are_per_request():
    client = ReviewingClient(
        reply(search()),
        reply(submit()),
        reply(search()),
        reply(submit()),
        verdicts=["SUPPORTED", "SUPPORTED"],
        known_usage=False,
    )
    service = ToolChatService(client, CommonKnowledge(), load_faq_catalog())
    ids = []
    for _ in range(2):
        question = ChatQuestion(request_id=uuid4(), question="점검 방법")
        assert (
            service.reply(question, context=ChatContext(), timeout_s=10).status == "OK"
        )
        ids.append(service.last_run.request_id)
        assert service.last_run.total is None and service.last_run.unknown_calls == 3
        assert len(service.last_run.calls) == 3
    assert ids[0] != ids[1]


def test_runtime_receives_the_real_tracer_through_budget_wrapper():
    observed = []

    class Tracer:
        @contextmanager
        def observe(self, name, **kwargs):
            observed.append((name, kwargs))
            yield type("Observation", (), {"update": lambda *a, **k: None})()

    client = ReviewingClient(reply(search()), reply(submit()))
    client.tracer = Tracer()
    assert ask(client).status == "OK"
    assert {name for name, _ in observed} >= {
        "chat-assistant",
        "search_knowledge",
        "submit_answer",
    }
    assert next(fields for name, fields in observed if name == "chat-assistant")[
        "session_id"
    ]


def test_retries_make_total_usage_uncertain_even_when_final_response_has_usage():
    client = ReviewingClient(reply(search()), reply(submit()))
    client.last_attempts = 2
    service = ToolChatService(client, CommonKnowledge(), load_faq_catalog())
    response = service.reply(
        ChatQuestion(request_id=uuid4(), question="점검 방법"),
        context=ChatContext(),
        timeout_s=10,
    )
    assert response.status == "OK"
    assert service.last_run.total is None
    assert service.last_run.unknown_calls == 3
    assert all(
        call.usage is not None and call.attempts == 2 for call in service.last_run.calls
    )


@pytest.mark.parametrize(
    "verdicts,status,checks",
    [
        (["SUPPORTED", "SUPPORTED", "SUPPORTED"], "OK", 1),
        (["UNSUPPORTED", "UNSUPPORTED", "SUPPORTED"], "INSUFFICIENT_EVIDENCE", 2),
    ],
)
def test_multiple_finish_calls_cannot_bypass_review_limit(verdicts, status, checks):
    client = ReviewingClient(
        reply(search()), reply(submit(), submit(), submit()), verdicts=verdicts
    )
    result = ask(client)
    assert result.status == status
    assert len(client.checks) == checks


def test_clarification_cannot_display_hidden_unverified_instructions():
    client = ReviewingClient(
        reply(
            submit(
                "NEEDS_CLARIFICATION",
                clarification_questions=[
                    "PRIVATE_UNSUPPORTED_INSTRUCTION: 교체 후 재가동하세요. 어느 설비인가요?"
                ],
            )
        )
    )
    result = ask(client)
    assert result.status == "NEEDS_CLARIFICATION"
    assert "PRIVATE_UNSUPPORTED_INSTRUCTION" not in result.model_dump_json()
    assert result.clarification_questions == [
        "찾으려는 자료와 설비 ID·오류 코드·조회 기간 중 필요한 조건을 알려주세요."
    ]
    assert not client.checks
