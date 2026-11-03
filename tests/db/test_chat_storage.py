"""실제 임시 DB로 소유권·동시 예약·재전송·실패 복구와 삭제 경계를 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from weeing_weeing.agent.interface import load_faq_catalog
from weeing_weeing.contracts import (
    ChatResponse,
    ChatSearchConditions,
    ChatSubmission,
    FaqSelection,
    Role,
    UserAccount,
)
from weeing_weeing.db import chats as module
from weeing_weeing.db.interface import ChatConflictError, ChatNotFoundError, open_chats
from weeing_weeing.db.models import (
    ChatConversationRow,
    ChatMessageRow,
    ChatRequestRow,
    LegacyChatFeedbackRow,
    UserRow,
)


@pytest.fixture
def chats(database_url, users):
    for no, admin in [("owner", False), ("other", False), ("admin", True)]:
        users.create_user(
            UserAccount(employee_no=no, name=no, role=Role.CONTROL, is_admin=admin),
            "test-password",
        )
    repo = open_chats(database_url)
    yield repo
    repo._engine.dispose()


def submission(**overrides):
    return ChatSubmission.model_validate(
        dict(request_id=uuid4(), kind="CHAT", question="센서 점검 방법은?") | overrides
    )


def response(request_id, **overrides):
    return ChatResponse.model_validate(
        dict(
            request_id=request_id,
            intent="MANUAL",
            status="INSUFFICIENT_EVIDENCE",
            applied_conditions={},
            message="근거가 부족합니다.",
            generated_at=datetime.now(UTC),
        )
        | overrides
    )


def completed(chats, *, kind="CHAT"):
    conversation = chats.create_conversation("owner", mode=kind)
    if kind == "FAQ":
        catalog = load_faq_catalog()
        question = catalog.list_questions(catalog.list_topics()[0].topic_id)[0]
        item = submission(
            kind="FAQ",
            question=None,
            faq_id=question.faq_id,
        )
        answer = catalog.answer(
            FaqSelection(
                request_id=item.request_id,
                faq_id=item.faq_id,
            )
        )
        kwargs = dict(question_text=question.question)
    else:
        item = submission()
        answer = response(item.request_id)
        kwargs = {}
    claim = chats.reserve_request("owner", conversation.conversation_id, item)
    chats.start_request(
        "owner", conversation.conversation_id, item.request_id, claim.execution_token
    )
    result = chats.complete_request(
        "owner",
        conversation.conversation_id,
        item.request_id,
        claim.execution_token,
        answer,
        **kwargs,
    )
    return conversation, item, claim, result


def test_completed_request_replays_without_new_messages(chats):
    c, item, claim, saved = completed(chats)
    replay = chats.reserve_request("owner", c.conversation_id, item, retry=True)
    assert replay.execution_token is None
    assert replay.request == saved
    assert (
        chats.complete_request(
            "owner",
            c.conversation_id,
            item.request_id,
            claim.execution_token,
            saved.response,
        )
        == saved
    )
    page = chats.get_conversation("owner", c.conversation_id)
    assert [(m.sequence, m.role) for m in page.messages] == [
        (1, "user"),
        (2, "assistant"),
    ]
    assert len(chats.get_context("owner", c.conversation_id).recent_turns) == 2
    assert chats.get_conversation("owner", c.conversation_id, limit=1).has_more
    assert (
        chats.get_conversation("owner", c.conversation_id, after_sequence=1)
        .messages[0]
        .sequence
        == 2
    )


@pytest.mark.parametrize("actor", ["other", "admin", "missing"])
def test_every_operation_is_owner_only_even_for_admin(chats, actor):
    c, item, claim, saved = completed(chats)
    cid, rid = c.conversation_id, item.request_id
    operations = [
        lambda: chats.get_conversation(actor, cid),
        lambda: chats.get_request(actor, cid, rid),
        lambda: chats.update_conversation(actor, cid, title="훔치기"),
        lambda: chats.delete_conversation(actor, cid),
        lambda: chats.get_context(actor, cid),
        lambda: chats.reserve_request(actor, cid, item),
        lambda: chats.start_request(actor, cid, rid, claim.execution_token),
        lambda: chats.fail_request(actor, cid, rid, claim.execution_token),
        lambda: chats.complete_request(
            actor, cid, rid, claim.execution_token, saved.response
        ),
    ]
    for operation in operations:
        with pytest.raises(ChatNotFoundError):
            operation()
    if actor != "missing":
        assert chats.list_conversations(actor) == []
    else:
        with pytest.raises(ChatNotFoundError):
            chats.list_conversations(actor)
    assert chats.get_request("owner", cid, rid).response == saved.response


def test_inactive_owner_cannot_read_or_create(chats, users):
    c = chats.create_conversation("owner")
    users.update_user("owner", is_active=False)
    for operation in [
        lambda: chats.get_conversation("owner", c.conversation_id),
        lambda: chats.create_conversation("owner"),
        lambda: chats.list_conversations("owner"),
    ]:
        with pytest.raises(ChatNotFoundError):
            operation()


def test_pending_duplicate_and_changed_body(chats):
    c = chats.create_conversation("owner", mode="CHAT")
    item = submission()
    first = chats.reserve_request("owner", c.conversation_id, item)
    assert first.execution_token
    duplicate = chats.reserve_request("owner", c.conversation_id, item)
    assert duplicate.execution_token is None and duplicate.request.state == "RESERVED"
    chats.start_request(
        "owner", c.conversation_id, item.request_id, first.execution_token
    )
    assert (
        chats.reserve_request("owner", c.conversation_id, item).request.state
        == "RUNNING"
    )
    with pytest.raises(ChatConflictError):
        chats.reserve_request(
            "owner",
            c.conversation_id,
            item.model_copy(update={"question": "다른 질문"}),
        )
    with pytest.raises(ChatConflictError):
        chats.reserve_request("owner", c.conversation_id, submission())
    with pytest.raises(ChatConflictError):
        chats.update_conversation("owner", c.conversation_id, mode="FAQ")


def test_concurrent_reservations_have_one_winner(chats):
    c = chats.create_conversation("owner", mode="CHAT")
    item = submission()
    barrier = Barrier(4)

    def reserve(_):
        barrier.wait()
        return chats.reserve_request("owner", c.conversation_id, item)

    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(reserve, range(4)))
    assert sum(c.execution_token is not None for c in claims) == 1
    assert len(chats.get_conversation("owner", c.conversation_id).messages) == 1


def test_preparation_failure_requires_explicit_retry(chats):
    c = chats.create_conversation("owner", mode="CHAT")
    item = submission()
    claim = chats.reserve_request("owner", c.conversation_id, item)
    failed = chats.fail_request(
        "owner", c.conversation_id, item.request_id, claim.execution_token
    )
    assert failed.state == "FAILED" and failed.retry_allowed
    assert (
        chats.reserve_request("owner", c.conversation_id, item).execution_token is None
    )
    retry = chats.reserve_request("owner", c.conversation_id, item, retry=True)
    assert retry.execution_token and retry.execution_token != claim.execution_token
    with pytest.raises(ChatConflictError):
        chats.start_request(
            "owner", c.conversation_id, item.request_id, claim.execution_token
        )
    assert len(chats.get_conversation("owner", c.conversation_id).messages) == 1


@pytest.mark.parametrize("started", [False, True])
def test_expiration_fences_late_worker_and_only_prestart_can_retry(
    chats, monkeypatch, started
):
    c = chats.create_conversation("owner", mode="CHAT")
    item = submission()
    claim = chats.reserve_request("owner", c.conversation_id, item)
    if started:
        chats.start_request(
            "owner", c.conversation_id, item.request_id, claim.execution_token
        )
    future = datetime.now(UTC) + timedelta(seconds=1000)
    monkeypatch.setattr(module, "now", lambda: future)
    expired = chats.get_request("owner", c.conversation_id, item.request_id)
    assert expired.state == ("UNKNOWN" if started else "FAILED")
    assert expired.retry_allowed is (not started)
    with pytest.raises(ChatConflictError):
        chats.complete_request(
            "owner",
            c.conversation_id,
            item.request_id,
            claim.execution_token,
            response(item.request_id),
        )
    retry = chats.reserve_request("owner", c.conversation_id, item, retry=True)
    assert (retry.execution_token is not None) is (not started)


def test_poststart_exception_is_unknown_and_not_retried(chats):
    c = chats.create_conversation("owner", mode="CHAT")
    item = submission()
    claim = chats.reserve_request("owner", c.conversation_id, item)
    chats.start_request(
        "owner", c.conversation_id, item.request_id, claim.execution_token
    )
    failed = chats.fail_request(
        "owner", c.conversation_id, item.request_id, claim.execution_token
    )
    assert failed.state == "UNKNOWN" and not failed.retry_allowed
    assert (
        chats.reserve_request(
            "owner", c.conversation_id, item, retry=True
        ).execution_token
        is None
    )
    assert chats.get_context("owner", c.conversation_id).recent_turns == []


def test_mode_conditions_and_replay_after_settings_change(chats):
    c = chats.create_conversation("owner")
    item = submission()
    with pytest.raises(ChatConflictError):
        chats.reserve_request("owner", c.conversation_id, item)
    chats.update_conversation(
        "owner",
        c.conversation_id,
        mode="CHAT",
        conditions=ChatSearchConditions(asset_id="P1"),
    )
    claim = chats.reserve_request("owner", c.conversation_id, item)
    assert claim.request.conditions.asset_id == "P1"
    chats.start_request(
        "owner", c.conversation_id, item.request_id, claim.execution_token
    )
    chats.complete_request(
        "owner",
        c.conversation_id,
        item.request_id,
        claim.execution_token,
        response(item.request_id),
    )
    chats.update_conversation(
        "owner",
        c.conversation_id,
        mode="FAQ",
        conditions=ChatSearchConditions(asset_id="P2"),
    )
    assert (
        chats.reserve_request(
            "owner", c.conversation_id, item
        ).request.conditions.asset_id
        == "P1"
    )


def test_faq_snapshot_and_cascade(chats):
    c, item, _, saved = completed(chats, kind="FAQ")
    assert (
        chats.get_conversation("owner", c.conversation_id).messages[0].content
        != f"FAQ 선택: {item.faq_id}"
    )
    chats.delete_conversation("owner", c.conversation_id)
    with chats._transaction() as session:
        for table in [
            ChatConversationRow,
            ChatRequestRow,
            ChatMessageRow,
            LegacyChatFeedbackRow,
        ]:
            assert session.scalar(select(func.count()).select_from(table)) == 0
        assert session.get(UserRow, "owner") is not None
    with pytest.raises(ChatNotFoundError):
        chats.get_request("owner", c.conversation_id, item.request_id)


def test_service_failed_response_is_saved_and_never_auto_replayed(chats):
    c = chats.create_conversation("owner", mode="CHAT")
    item = submission()
    claim = chats.reserve_request("owner", c.conversation_id, item)
    chats.start_request(
        "owner", c.conversation_id, item.request_id, claim.execution_token
    )
    answer = response(
        item.request_id, status="FAILED", failure=dict(code="TIMEOUT", retryable=True)
    )
    saved = chats.complete_request(
        "owner", c.conversation_id, item.request_id, claim.execution_token, answer
    )
    assert saved.state == "COMPLETED" and not saved.retry_allowed
    assert (
        chats.reserve_request(
            "owner", c.conversation_id, item, retry=True
        ).execution_token
        is None
    )
    assert chats.get_context("owner", c.conversation_id).recent_turns == []


def test_context_limit_and_request_id_scope(chats):
    first = chats.create_conversation("owner", mode="CHAT")
    last_item = None
    for _ in range(8):
        last_item = submission(question="질" * 2000)
        claim = chats.reserve_request("owner", first.conversation_id, last_item)
        chats.start_request(
            "owner", first.conversation_id, last_item.request_id, claim.execution_token
        )
        chats.complete_request(
            "owner",
            first.conversation_id,
            last_item.request_id,
            claim.execution_token,
            response(last_item.request_id, message="답" * 5000),
        )
    context = chats.get_context("owner", first.conversation_id)
    assert 0 < len(context.recent_turns) <= 20
    assert sum(len(t.content) for t in context.recent_turns) <= 16000
    assert max(len(t.content) for t in context.recent_turns) <= 4000
    assert [t.role for t in context.recent_turns] == ["user", "assistant"] * (
        len(context.recent_turns) // 2
    )
    second = chats.create_conversation("owner", mode="CHAT")
    assert (
        chats.reserve_request(
            "owner", second.conversation_id, last_item
        ).execution_token
        is not None
    )


def test_migration_roundtrip_preserves_existing_users(chats):
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect

    from weeing_weeing.db.migrate import alembic_config
    from weeing_weeing.db.models import Base

    config = alembic_config()
    with chats._engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0006")
        assert not inspect(connection).has_table("chat_conversation")
        assert connection.scalar(select(func.count()).select_from(UserRow)) == 3
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert (
            compare_metadata(MigrationContext.configure(connection), Base.metadata)
            == []
        )
    assert chats.create_conversation("owner").mode == "FAQ"


def test_legacy_data_is_preserved_while_unused_by_storage(chats):
    c, item, _, saved = completed(chats)
    legacy_usage = {"input_tokens": 123}
    with chats._transaction() as session:
        session.execute(
            update(ChatRequestRow)
            .where(
                ChatRequestRow.conversation_id == str(c.conversation_id),
                ChatRequestRow.request_id == str(item.request_id),
            )
            .values(usage=legacy_usage)
        )
        session.add(
            LegacyChatFeedbackRow(
                conversation_id=str(c.conversation_id),
                request_id=str(item.request_id),
                rating="HELPFUL",
                comment="기존 의견",
                updated_at=datetime.now(UTC),
            )
        )
    assert (
        chats.get_request("owner", c.conversation_id, item.request_id).response
        == saved.response
    )
    assert (
        chats.reserve_request("owner", c.conversation_id, item).execution_token is None
    )
    assert (
        "usage"
        not in chats.get_request(
            "owner", c.conversation_id, item.request_id
        ).model_dump()
    )
    assert len(chats.get_conversation("owner", c.conversation_id).messages) == 2
    with chats._transaction() as session:
        assert (
            session.get(
                ChatRequestRow, (str(c.conversation_id), str(item.request_id))
            ).usage
            == legacy_usage
        )
        assert (
            session.get(
                LegacyChatFeedbackRow, (str(c.conversation_id), str(item.request_id))
            ).comment
            == "기존 의견"
        )


def test_legacy_faq_version_is_ignored_on_read_and_duplicate_replay(chats):
    conversation, item, claim, saved = completed(chats, kind="FAQ")
    cid, rid = str(conversation.conversation_id), str(item.request_id)
    legacy_response = saved.response.model_dump(mode="json")
    legacy_response["sources"][0]["faq_version"] = "old"
    legacy_submission = item.model_dump(mode="json") | {"faq_version": "old"}
    with chats._transaction() as session:
        row = session.get(ChatRequestRow, (cid, rid))
        row.submission = legacy_submission
        row.response = legacy_response
        row.fingerprint = (
            "0" * 64
        )  # 이전 버전을 포함해 생성됐던 해시는 새 본문과 다르다.
    loaded = chats.get_request("owner", cid, rid)
    assert loaded.response == saved.response
    assert "faq_version" not in loaded.submission.model_dump()
    assert "faq_version" not in loaded.response.sources[0].model_dump()
    replay = chats.reserve_request("owner", cid, item)
    assert replay.execution_token is None and replay.request.response == saved.response
    assert chats.get_conversation("owner", cid).messages[1].response == saved.response
    assert len(chats.get_context("owner", cid).recent_turns) == 2
    assert (
        chats.complete_request(
            "owner", cid, rid, claim.execution_token, loaded.response
        )
        == loaded
    )
    with chats._transaction() as session:
        row = session.get(ChatRequestRow, (cid, rid))
        assert row.submission == legacy_submission and row.response == legacy_response
