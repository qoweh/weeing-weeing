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
    assert "작성한 답변" in response.message
    assert "자료가 없" not in response.message


def test_conflicting_evidence_asks_instead_of_combining_claims():
    reason = "검색된 절차의 적용 조건이 달라 하나의 작업 순서로 합칠 수 없습니다."
    questions = ["현재 적용하려는 문서 버전을 알려주시겠어요?"]
    client = ReviewingClient(
        reply(search()),
        reply(submit()),
        reply(
            submit(
                "NEEDS_CLARIFICATION", message=reason, clarification_questions=questions
            )
        ),
        verdicts=["CONFLICT", "SUPPORTED"],
    )
    response = ask(client)
    assert response.status == "NEEDS_CLARIFICATION"
    assert response.message == reason
    assert response.clarification_questions == questions and not response.parts
    assert client.checks[-1]["mode"] == "CLARIFICATION"


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
                message="근거 없이 특정 고장이라고 단정하는 이유",
                clarification_questions=[
                    "PRIVATE_UNSUPPORTED_INSTRUCTION: 교체 후 재가동하세요. 어느 설비인가요?"
                ],
            )
        ),
        reply(search()),
        reply(submit()),
        verdicts=["UNSUPPORTED", "SUPPORTED"],
    )
    result = ask(client)
    assert result.status == "OK"
    assert "PRIVATE_UNSUPPORTED_INSTRUCTION" not in result.model_dump_json()
    assert client.checks[0]["mode"] == "CLARIFICATION"
    assert "mode" not in client.checks[1]


@pytest.mark.parametrize(
    "question,reason,questions",
    [
        (
            "그걸 어떻게 확인해?",
            "현재 대화에는 '그것'이 어떤 현상을 가리키는지 나와 있지 않습니다.",
            ["확인하려는 현상이나 앞서 말씀하신 대상을 알려주시겠어요?"],
        ),
        (
            "지난달 보고서만, 올해 전체 기간으로 알려줘",
            "지난달만 조회할지 올해 전체를 조회할지 기간 조건이 서로 다릅니다.",
            ["조회 기간을 지난달과 올해 전체 중에서 선택해 주세요."],
        ),
    ],
)
def test_clarification_preserves_reviewed_specific_reason_and_questions(
    question, reason, questions
):
    client = ReviewingClient(
        reply(
            submit(
                "NEEDS_CLARIFICATION", message=reason, clarification_questions=questions
            )
        ),
    )
    service = ToolChatService(client, CommonKnowledge(), load_faq_catalog())
    result = service.reply(
        ChatQuestion(request_id=uuid4(), question=question),
        context=ChatContext(),
        timeout_s=10,
    )
    assert result.status == "NEEDS_CLARIFICATION"
    assert result.message == reason and result.clarification_questions == questions
    assert client.checks[0]["question"] == question
    assert client.checks[0]["parts"] == [
        {"text": text} for text in [reason, *questions]
    ]
    assert not result.parts and not result.sources
    assert service.last_run.calls[-1].purpose == "grounding"


def test_optional_filters_are_not_a_reason_to_require_clarification():
    client = ReviewingClient(
        reply(
            submit(
                "NEEDS_CLARIFICATION",
                message="설비 ID와 기간을 입력하지 않았습니다.",
                clarification_questions=["설비 ID와 기간을 모두 알려주세요."],
            )
        ),
        reply(search()),
        reply(submit()),
        verdicts=["UNSUPPORTED", "SUPPORTED"],
    )
    knowledge = CommonKnowledge()
    result = ask(client, knowledge)
    assert result.status == "OK"
    assert knowledge.searches[0].conditions.asset_id is None
    assert knowledge.searches[0].conditions.date_from is None


def test_repeated_unverified_clarification_is_not_shown_to_user():
    invalid = reply(
        submit(
            "NEEDS_CLARIFICATION",
            message="UNVERIFIED_REASON",
            clarification_questions=["UNVERIFIED_QUESTION"],
        )
    )
    client = ReviewingClient(
        invalid, invalid, invalid, verdicts=["UNSUPPORTED", "UNSUPPORTED"]
    )
    result = ask(client)
    assert result.failure.code == "INVALID_RESPONSE"
    assert "UNVERIFIED" not in result.model_dump_json()
    assert len(client.checks) == 2


@pytest.mark.parametrize(
    "has_results,message",
    [
        (False, "입구 센서 점검 자료를 검색했지만 찾지 못했습니다."),
        (
            True,
            "검색된 자료는 센서 점검 절차여서, 외함 온도의 복구 측정 결과는 확인할 수 없습니다.",
        ),
    ],
)
def test_insufficient_evidence_preserves_reviewed_specific_explanation(
    has_results, message
):
    knowledge = CommonKnowledge() if has_results else CommonKnowledge(hits=[])
    client = ReviewingClient(
        reply(search()), reply(submit("INSUFFICIENT_EVIDENCE", message=message))
    )
    service = ToolChatService(client, knowledge, load_faq_catalog())
    result = service.reply(
        ChatQuestion(
            request_id=uuid4(),
            question="외함 온도의 복구 측정 결과를 알려줘"
            if has_results
            else "입구 센서 점검 절차를 알려줘",
        ),
        context=ChatContext(),
        timeout_s=10,
    )
    assert result.status == "INSUFFICIENT_EVIDENCE" and result.message == message
    assert not result.parts and not result.sources
    payload = client.checks[0]
    assert payload["mode"] == "INSUFFICIENCY"
    assert payload["retrievals"][0]["returned"] == int(has_results)
    assert bool(payload["evidence"]) == has_results


def test_partially_answerable_question_returns_supported_part_and_limitation():
    from test_chat_service import document

    hit = document()
    hit.text = "외함 방열 통로를 청소했다."
    client = ReviewingClient(
        reply(search()),
        reply(
            submit(
                text="방열 통로를 청소했습니다. 다만 이 자료에는 조치 후 온도 측정 결과가 없어 복구 여부는 확인할 수 없습니다."
            )
        ),
    )
    service = ToolChatService(client, CommonKnowledge(hits=[hit]), load_faq_catalog())
    result = service.reply(
        ChatQuestion(
            request_id=uuid4(), question="외함 온도 문제의 조치와 복구 결과를 알려줘"
        ),
        context=ChatContext(),
        timeout_s=10,
    )
    assert result.status == "OK"
    assert "청소" in result.parts[0].text and "확인할 수 없" in result.parts[0].text
    assert result.parts[0].source_ids == [hit.source.source_id]
    assert client.checks[0]["evidence"][hit.source.source_id]["text"] == hit.text


def test_unverified_insufficiency_explanation_is_rewritten_not_displayed():
    client = ReviewingClient(
        reply(search()),
        reply(
            submit(
                "INSUFFICIENT_EVIDENCE",
                message="PRIVATE_UNSUPPORTED_CLAIM: 전체 시스템에 온도 기록이 없습니다. 즉시 재가동하세요.",
            )
        ),
        reply(
            submit(
                "INSUFFICIENT_EVIDENCE",
                message="검색된 자료는 센서 점검 절차여서, 온도 측정 기록을 확인할 수 없습니다.",
            )
        ),
        verdicts=["UNSUPPORTED", "SUPPORTED"],
    )
    result = ask(client)
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert "PRIVATE_UNSUPPORTED" not in result.model_dump_json()
    assert "검색된 자료" in result.message
    assert len(client.checks) == 2


def test_insufficient_evidence_requires_retrieval_before_claiming_no_results():
    client = ReviewingClient(
        reply(submit("INSUFFICIENT_EVIDENCE", message="관련 자료를 찾지 못했습니다.")),
        reply(search()),
        reply(
            submit(
                "INSUFFICIENT_EVIDENCE",
                message="입구 센서 점검 자료를 찾지 못했습니다.",
            )
        ),
    )
    knowledge = CommonKnowledge(hits=[])
    result = ask(client, knowledge)
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert len(knowledge.searches) == 1
    assert len(client.checks) == 1


def test_unverified_insufficiency_explanations_have_bounded_review_attempts():
    invalid = reply(submit("INSUFFICIENT_EVIDENCE", message="UNVERIFIED_REASON"))
    client = ReviewingClient(
        reply(search()),
        invalid,
        invalid,
        invalid,
        verdicts=["UNSUPPORTED", "UNSUPPORTED"],
    )
    result = ask(client, CommonKnowledge(hits=[]))
    assert result.failure.code == "INVALID_RESPONSE"
    assert "UNVERIFIED_REASON" not in result.model_dump_json()
    assert len(client.checks) == 2
