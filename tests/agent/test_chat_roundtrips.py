"""재검색 범위·수정 피드백·계측 검증. 실제 LLM은 호출하지 않는다."""

import json
from uuid import uuid4

import pytest
from test_chat_service import CommonKnowledge, FakeClient, reply, search, submit
from test_chat_validation import ReviewingClient

from weeing_weeing.agent.chat import ToolChatService
from weeing_weeing.agent.chat_grounding import verify_grounding
from weeing_weeing.agent.interface import load_faq_catalog
from weeing_weeing.contracts import ChatContext, ChatQuestion
from weeing_weeing.contracts.chat_tools import ChatHistoryResult


class EmptyHistory(CommonKnowledge):
    def __init__(self, *, total=0, stale=False, mismatch=False):
        super().__init__(hits=[])
        self.total = total
        self.stale = stale
        self.mismatch = mismatch
        self.scopes = []

    def query_history(self, query, *, timeout_s):
        self.scopes.append(query)
        conditions = query.conditions.model_copy(deep=True)
        if self.mismatch:
            conditions.asset_id = "WRONG"
        return ChatHistoryResult(
            source={
                "kind": "HISTORY_QUERY",
                "source_id": "scope:zero",
                "title": "현재 조건의 승인 이력 조회",
                "conditions": conditions,
                "code": query.code,
                "total": self.total,
                "synthetic_total": 0,
                "snapshot": "a" * 64,
            },
            reports=[
                {
                    "source": {
                        "kind": "REPORT",
                        "source_id": "report:1",
                        "title": "다른 조치 이력",
                        "report_id": "RPT-1",
                        "report_version": 1,
                        "synthetic": False,
                    },
                    "text": "광전센서 렌즈를 청소했습니다.",
                }
            ]
            if self.total
            else [],
            truncated=False,
        )

    def is_searchable(self, source, *, timeout_s):
        self.reads.append(source)
        return not self.stale


def run(client, knowledge=None):
    service = ToolChatService(
        client, knowledge or CommonKnowledge(), load_faq_catalog()
    )
    result = service.reply(
        ChatQuestion(request_id=uuid4(), question="과거 RPM 저하 이력은?"),
        context=ChatContext(),
        timeout_s=10,
    )
    return result, service.last_run


def tool_results(client):
    return [
        b
        for m in client.calls[-1]["messages"]
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if b["type"] == "tool_result"
    ]


def test_empty_history_returns_citable_scope_in_same_tool_turn():
    knowledge = EmptyHistory()
    client = ReviewingClient(
        reply(search("MAINTENANCE_HISTORY", code="BTT2-M02")),
        reply(
            submit(
                intent="MAINTENANCE_HISTORY",
                ids=("scope:zero",),
                text="조회 조건에 맞는 최신 승인 보고서는 0건입니다.",
            )
        ),
    )
    result, usage = run(client, knowledge)
    assert result.status == "OK"
    assert len(client.calls) == 2 and len(usage.calls) == 3
    assert len(knowledge.scopes) == 1
    assert knowledge.scopes[0].code == "BTT2-M02"
    payload = json.loads(tool_results(client)[0]["content"])
    assert payload["availability"] == "NO_CANDIDATES" and payload["hits"] == []
    assert payload["scope_source"]["total"] == 0
    assert result.sources[0].kind == "HISTORY_QUERY"
    assert len(knowledge.reads) == 3  # 조회 직후·제출 전·검토 후 그대로 확인


@pytest.mark.parametrize("option", ["stale", "mismatch"])
def test_invalid_or_stale_scope_fails_closed(option):
    result, _ = run(
        FakeClient(reply(search("MAINTENANCE_HISTORY"))), EmptyHistory(**{option: True})
    )
    assert result.status == "FAILED"
    assert result.failure.code == "SEARCH_UNAVAILABLE"


def test_legacy_empty_search_does_not_invent_zero_candidate_count():
    client = FakeClient(reply(search()), reply(submit("INSUFFICIENT_EVIDENCE")))
    result, _ = run(client, CommonKnowledge(hits=[]))
    assert result.status == "INSUFFICIENT_EVIDENCE"
    payload = json.loads(tool_results(client)[0]["content"])
    assert payload["availability"] == "NO_RESULTS"
    assert payload["scope_source"] is None


def test_existing_candidates_with_no_search_results_are_not_reported_as_absent():
    client = FakeClient(
        reply(search("MAINTENANCE_HISTORY")), reply(submit("INSUFFICIENT_EVIDENCE"))
    )
    result, _ = run(client, EmptyHistory(total=1))
    assert result.status == "INSUFFICIENT_EVIDENCE"
    payload = json.loads(tool_results(client)[0]["content"])
    assert payload["availability"] == "NO_MATCHES"
    assert payload["scope_source"] is None and payload["hits"] == []
    assert not result.sources


def test_zero_scope_is_rechecked_after_review():
    class Changed(EmptyHistory):
        def is_searchable(self, source, *, timeout_s):
            super().is_searchable(source, timeout_s=timeout_s)
            return len(self.reads) < 3

    client = ReviewingClient(
        reply(search("MAINTENANCE_HISTORY")),
        reply(
            submit(
                intent="MAINTENANCE_HISTORY",
                ids=("scope:zero",),
                text="조회 조건의 승인 보고서는 0건입니다.",
            )
        ),
    )
    result, _ = run(client, Changed())
    assert result.failure.code == "SEARCH_UNAVAILABLE"


def test_targeted_feedback_and_metadata_preserve_review_on_rewrite():
    class Issues(ReviewingClient):
        def generate_json(self, system, user, **kwargs):
            value = super().generate_json(system, user, **kwargs)
            if len(self.checks) == 1:
                return json.dumps(
                    {
                        "verdict": "UNSUPPORTED",
                        "unsupported_parts": [0],
                        "issues": [{"part": 0, "reason": "UNSUPPORTED_CLAIM"}],
                    }
                )
            return value

    client = Issues(
        reply(search()),
        reply(submit(text="必ず交換 PRIVATE_BODY")),
        reply(submit()),
        verdicts=["UNSUPPORTED", "SUPPORTED"],
    )
    result, usage = run(client)
    assert result.status == "OK" and len(client.checks) == 2
    errors = [b["content"] for b in tool_results(client) if b["is_error"]]
    assert any("부분 0" in e and "근거에 없는 단정" in e for e in errors)
    assert usage.reviews[0].reasons == ("UNSUPPORTED_CLAIM",)
    assert usage.reviews[0].unsupported_parts == (0,)
    assert usage.reviews[1].verdict == "SUPPORTED"
    assert "PRIVATE_BODY" not in repr(usage)


def test_invalid_submission_shape_does_not_spend_review_budget():
    invalid = reply(submit("NEEDS_CLARIFICATION", intent="OUT_OF_SCOPE"))
    valid = reply(
        submit(
            "NEEDS_CLARIFICATION",
            intent="COMBINED",
            message="현재 질문에서 어떤 문제를 지칭하는지 확인되지 않습니다.",
            clarification_questions=["어떤 문제나 알림을 말씀하시나요?"],
        )
    )
    client = ReviewingClient(invalid, invalid, valid, verdicts=["SUPPORTED"])
    result, usage = run(client)
    assert result.status == "NEEDS_CLARIFICATION"
    assert len(client.checks) == 1
    assert len(usage.calls) == 4  # 대화 3회 + 유효 응답의 근거 검토 1회
    assert len(usage.reviews) == 1
    assert all(
        "응답 상태·의도" in b["content"] for b in tool_results(client) if b["is_error"]
    )


@pytest.mark.parametrize(
    "issues",
    [
        [{"part": 1, "reason": "UNSUPPORTED_CLAIM"}],
        [{"part": 0, "reason": "FREE_TEXT_INSTRUCTIONS"}],
        [{"part": True, "reason": "UNSUPPORTED_CLAIM"}],
    ],
)
def test_malformed_repair_reasons_fail_closed(issues):
    class Invalid(FakeClient):
        def generate_json(self, *args, **kwargs):
            return json.dumps(
                {"verdict": "UNSUPPORTED", "unsupported_parts": [0], "issues": issues}
            )

    with pytest.raises(Exception, match="근거 검토 응답 형식 오류"):
        verify_grounding(Invalid(), {"parts": [{"text": "x"}]}, timeout_s=5)
