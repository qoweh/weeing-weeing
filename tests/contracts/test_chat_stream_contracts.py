from uuid import uuid4

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts.chat_stream import ChatStreamDelta, ChatStreamProgress


def test_delta_preserves_markdown_boundary_whitespace():
    event = ChatStreamDelta(request_id=uuid4(), text="\n\n  **온도** ")
    assert event.text == "\n\n  **온도** "
    assert ChatStreamDelta.model_validate_json(event.model_dump_json()) == event


def test_progress_has_only_known_phases_and_no_draft_payload():
    with pytest.raises(ValidationError):
        ChatStreamProgress(request_id=uuid4(), phase="provider_raw")
    with pytest.raises(ValidationError):
        ChatStreamProgress(request_id=uuid4(), phase="verifying", draft="unverified")
