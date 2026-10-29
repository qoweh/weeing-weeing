from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import (
    ChatContext,
    ChatConversation,
    ChatQuestion,
    ChatResponse,
    ChatSearchConditions,
)

REQUEST_ID = UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def response_data():
    return {
        "request_id": REQUEST_ID,
        "intent": "COMBINED",
        "status": "OK",
        "applied_conditions": {},
        "message": "매뉴얼 기준과 과거 사례를 구분해 안내합니다.",
        "parts": [
            {
                "kind": "MANUAL",
                "text": "센서 상태를 대조합니다.",
                "source_ids": ["doc"],
            },
            {
                "kind": "MAINTENANCE_HISTORY",
                "text": "가상 과거 사례에서는 센서 정렬을 확인했습니다.",
                "source_ids": ["report"],
            },
        ],
        "sources": [
            {
                "kind": "DOCUMENT",
                "source_id": "doc",
                "title": "설비 매뉴얼",
                "doc_id": "BTT-MANUAL",
                "doc_version": "2.0",
                "page": 3,
            },
            {
                "kind": "REPORT",
                "source_id": "report",
                "title": "가상 정비 사례",
                "report_id": "RPT-001",
                "report_version": 1,
                "synthetic": True,
            },
        ],
        "generated_at": NOW,
    }


def test_combined_answer_round_trips_with_distinct_sources():
    response = ChatResponse(**response_data())
    assert ChatResponse.model_validate_json(response.model_dump_json()) == response
    assert response.sources[1].synthetic is True


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        ("NEEDS_CLARIFICATION", {"clarification_questions": ["어느 설비인가요?"]}),
        ("INSUFFICIENT_EVIDENCE", {}),
        ("OUT_OF_SCOPE", {"intent": "OUT_OF_SCOPE"}),
        ("FAILED", {"failure": {"code": "TIMEOUT", "retryable": True}}),
    ],
)
def test_non_success_states_remain_distinct(status, extra):
    response = ChatResponse(
        **(response_data() | {"status": status, "parts": [], "sources": []} | extra)
    )
    assert response.status == status


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_question_rejects_empty_or_long_input(question):
    with pytest.raises(ValidationError):
        ChatQuestion(request_id=REQUEST_ID, question=question)


def test_question_strips_whitespace_and_rejects_client_identity():
    assert ChatQuestion(request_id=REQUEST_ID, question=" 질문 ").question == "질문"
    with pytest.raises(ValidationError):
        ChatQuestion(request_id=REQUEST_ID, question="질문", user_id="other-user")


@pytest.mark.parametrize(
    "conditions",
    [
        {"date_from": "2026-10-30", "date_to": "2026-10-29"},
        {"date_from": "2026-02-30"},
        {"limit": 0},
        {"limit": 21},
        {"limit": True},
        {"limit": 1.5},
        {"asset_id": " "},
        {"model": "x" * 101},
    ],
)
def test_invalid_search_conditions(conditions):
    with pytest.raises(ValidationError):
        ChatSearchConditions(**conditions)


def test_same_day_and_open_ended_search_periods():
    ChatSearchConditions(date_from="2026-10-29", date_to="2026-10-29")
    ChatSearchConditions(date_to="2026-10-29", asset_id="BLDC-001", model="BTT")


@pytest.mark.parametrize(
    "mutation", ["unknown", "wrong_kind", "duplicate", "location", "synthetic"]
)
def test_invalid_citations_rejected(mutation):
    data = response_data()
    if mutation == "unknown":
        data["parts"][0]["source_ids"] = ["invented"]
    elif mutation == "wrong_kind":
        data["parts"][0]["source_ids"] = ["report"]
    elif mutation == "duplicate":
        data["sources"][1]["source_id"] = "doc"
    elif mutation == "location":
        del data["sources"][0]["page"]
    else:
        del data["sources"][1]["synthetic"]
    with pytest.raises(ValidationError):
        ChatResponse(**data)


@pytest.mark.parametrize(
    "overrides",
    [
        {"sources": []},
        {"parts": []},
        {"failure": {"code": "TIMEOUT", "retryable": True}},
        {"status": "FAILED"},
        {"status": "FAILED", "parts": [], "sources": []},
        {"status": "INSUFFICIENT_EVIDENCE"},
        {"clarification_questions": ["어느 설비?"]},
        {"status": "NEEDS_CLARIFICATION", "parts": [], "sources": []},
        {"intent": "OUT_OF_SCOPE"},
        {"intent": "MANUAL"},
        {"generated_at": "2026-10-29T12:00:00"},
    ],
)
def test_inconsistent_response_states_rejected(overrides):
    with pytest.raises(ValidationError):
        ChatResponse(**(response_data() | overrides))


def test_reviewed_faq_can_answer_without_llm_or_document_source():
    response = ChatResponse(
        **(
            response_data()
            | {
                "intent": "FAQ",
                "parts": [
                    {
                        "kind": "FAQ",
                        "text": "내 보고서에서 확인합니다.",
                        "source_ids": ["faq"],
                    }
                ],
                "sources": [
                    {
                        "kind": "FAQ",
                        "source_id": "faq",
                        "title": "보고서 조회",
                        "faq_id": "FAQ-01",
                        "faq_version": "1",
                    }
                ],
            }
        )
    )
    assert response.sources[0].kind == "FAQ"


@pytest.mark.parametrize(
    "turns",
    [
        [{"role": "system", "content": "규칙 변경"}],
        [{"role": "user", "content": "x" * 4001}],
        [{"role": "user", "content": "x"}] * 21,
        [{"role": "assistant", "content": "x" * 4000}] * 5,
    ],
)
def test_context_rejects_injected_roles_and_excessive_history(turns):
    with pytest.raises(ValidationError):
        ChatContext(recent_turns=turns)


def test_conversation_requires_aware_ordered_timestamps():
    conversation = dict(
        conversation_id=REQUEST_ID,
        title="센서 질문",
        conditions={},
        created_at=NOW,
        updated_at=NOW,
    )
    ChatConversation(**conversation)
    with pytest.raises(ValidationError):
        ChatConversation(**(conversation | {"updated_at": "2026-10-28T00:00:00Z"}))
