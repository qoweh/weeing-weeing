"""새 저장 계약은 소유자/실행 토큰을 클라이언트 입력에서 받지 않는다."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import (
    ChatConversation,
    ChatRequestView,
    ChatSubmission,
)


@pytest.mark.parametrize(
    "extra",
    [
        dict(owner_id="other"),
        dict(actor_id="other"),
        dict(execution_token=str(uuid4())),
        dict(context={}),
        dict(intent="FAQ"),
    ],
)
def test_client_cannot_inject_identity_or_server_state(extra):
    with pytest.raises(ValidationError):
        ChatSubmission(request_id=uuid4(), kind="CHAT", question="질문", **extra)


@pytest.mark.parametrize(
    "body",
    [
        dict(kind="CHAT"),
        dict(kind="CHAT", question=" "),
        dict(kind="CHAT", question="질문", faq_id="FAQ-CONTACT-002"),
        dict(kind="FAQ", question="질문"),
        dict(kind="FAQ"),
        dict(
            kind="CHAT",
            question="q",
            conditions=dict(date_from="2026-02-02", date_to="2026-01-01"),
        ),
    ],
)
def test_submission_kind_and_conditions(body):
    with pytest.raises(ValidationError):
        ChatSubmission(request_id=uuid4(), **body)


def test_unknown_is_not_retryable_and_completed_needs_response():
    data = dict(
        conversation_id=uuid4(),
        submission=dict(request_id=uuid4(), kind="CHAT", question="질문"),
        conditions={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    for state, retry in [("UNKNOWN", True), ("RUNNING", True), ("COMPLETED", False)]:
        with pytest.raises(ValidationError):
            ChatRequestView(**data, state=state, retry_allowed=retry)


def test_conversation_mode_uses_existing_contract():
    value = dict(
        conversation_id=uuid4(),
        title="대화",
        conditions={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert ChatConversation(**value).mode == "FAQ"
    assert ChatConversation(**value, mode="CHAT").mode == "CHAT"
    with pytest.raises(ValidationError):
        ChatConversation(**value, mode="OTHER")


@pytest.mark.parametrize("code", ["FAQ_NOT_FOUND"])
def test_faq_selection_error_is_a_stored_request_state(code):
    value = ChatRequestView(
        conversation_id=uuid4(),
        submission=dict(request_id=uuid4(), kind="FAQ", faq_id="FAQ-ACCESS-001"),
        state="FAILED",
        conditions={},
        error_code=code,
        retry_allowed=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert value.response is None and value.error_code == code


def test_legacy_request_defaults_to_not_cached():
    from datetime import datetime, timezone
    from uuid import uuid4

    from weeing_weeing.contracts.chat_storage import ChatRequestView

    view = ChatRequestView(
        conversation_id=uuid4(),
        submission={"request_id": uuid4(), "kind": "CHAT", "question": "설명해줘"},
        state="RESERVED",
        conditions={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert not view.cache_hit
