"""인증 후 조립 계층 테스트. API 키·모델·실제 DB 없이 임시 SQLite와 가짜 서비스만 쓴다."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event
from uuid import uuid4

import pytest

from weeing_weeing.agent.interface import (
    load_faq_catalog,
)
from weeing_weeing.api.chat_storage import StoredChatService
from weeing_weeing.contracts import ChatResponse, ChatSubmission, Role, UserAccount
from weeing_weeing.db.interface import (
    ChatNotFoundError,
    DatabaseUnavailableError,
    open_chats,
    open_users,
)


class FakeService:
    def __init__(self, *, error=False):
        self.calls = 0
        self.error = error
        self.contexts = []

    def reply(self, question, *, context, timeout_s):
        self.calls += 1
        self.contexts.append(context)
        if self.error:
            raise RuntimeError("provider-private-payload")
        return ChatResponse(
            request_id=question.request_id,
            intent="MANUAL",
            status="OK",
            applied_conditions=question.conditions,
            message="근거 안내",
            parts=[dict(kind="MANUAL", text="점검 절차", source_ids=["doc:1"])],
            sources=[
                dict(
                    kind="DOCUMENT",
                    source_id="doc:1",
                    title="매뉴얼",
                    doc_id="DOC",
                    doc_version="1",
                    page=1,
                )
            ],
            generated_at=datetime.now(UTC),
        )


@pytest.fixture
def setup(tmp_path):

    url = f"sqlite:///{tmp_path / 'chat.db'}"
    users = open_users(url)
    for no in ["owner", "other"]:
        users.create_user(
            UserAccount(employee_no=no, name=no, role=Role.INSPECTOR), "test-password"
        )
    repo = open_chats(url)
    service = FakeService()
    app = StoredChatService(repo, service_factory=lambda: service)
    c = repo.create_conversation("owner", mode="CHAT")
    yield repo, service, app, c.conversation_id
    repo._engine.dispose()
    users._engine.dispose()


def item():
    return ChatSubmission(request_id=uuid4(), kind="CHAT", question="센서 점검은?")


def test_replay_does_not_generate_and_next_question_receives_owned_context(setup):
    repo, service, app, cid = setup
    q = item()
    result = app.submit("owner", cid, q)
    assert result.state == "COMPLETED"
    for _ in range(3):
        replay = app.submit("owner", cid, q, retry=True)
        assert replay.response == result.response
    assert service.calls == 1
    app.submit("owner", cid, item())
    assert len(service.contexts[1].recent_turns) == 2
    assert repo.get_conversation("owner", cid).messages[0].content == q.question


def test_cross_owner_rejected_before_llm(setup):
    repo, service, app, cid = setup
    q = item()
    app.submit("owner", cid, q)
    for operation in [
        lambda: app.submit("other", cid, q),
        lambda: repo.get_request("other", cid, q.request_id),
        lambda: repo.get_conversation("other", cid),
    ]:
        with pytest.raises(ChatNotFoundError):
            operation()
    assert service.calls == 1


def test_faq_snapshot_replay_needs_no_catalog_llm_or_search(setup):
    repo, service, _, cid = setup
    repo.update_conversation("owner", cid, mode="FAQ")
    catalog = load_faq_catalog()
    question = catalog.list_questions(catalog.list_topics()[0].topic_id)[0]

    def forbidden():
        raise AssertionError("FAQ에서 외부 호출 금지")

    app = StoredChatService(repo, faq=catalog, service_factory=forbidden)
    q = ChatSubmission(
        request_id=uuid4(),
        kind="FAQ",
        faq_id=question.faq_id,
    )
    result = app.submit("owner", cid, q)
    assert result.state == "COMPLETED" and service.calls == 0

    class GoneCatalog:
        def answer(self, *args, **kwargs):
            raise AssertionError("저장된 FAQ 재응답 금지")

    app._faq = GoneCatalog()
    replay = app.submit("owner", cid, q)
    assert replay.response == result.response
    assert repo.get_conversation("owner", cid).messages[0].content == question.question


def test_preparation_failure_is_explicit_retry_only(setup):
    repo, service, app, cid = setup

    def broken():
        raise RuntimeError("secret-config-details")

    app._service_factory = broken
    q = item()
    failed = app.submit("owner", cid, q)
    assert failed.state == "FAILED" and failed.retry_allowed
    assert "secret" not in failed.model_dump_json()
    app._service_factory = lambda: service
    assert app.submit("owner", cid, q).state == "FAILED" and service.calls == 0
    assert (
        app.submit("owner", cid, q, retry=True).state == "COMPLETED"
        and service.calls == 1
    )
    assert len(repo.get_conversation("owner", cid).messages) == 2


def test_exception_after_start_is_unknown_and_never_reruns(setup):
    _, service, app, cid = setup
    service.error = True
    q = item()
    result = app.submit("owner", cid, q)
    assert result.state == "UNKNOWN" and not result.retry_allowed
    assert "provider-private" not in result.model_dump_json()
    assert (
        app.submit("owner", cid, q, retry=True).state == "UNKNOWN"
        and service.calls == 1
    )


def test_database_failure_after_generation_does_not_trigger_second_generation(
    setup, monkeypatch
):
    repo, service, app, cid = setup

    def broken(*args, **kwargs):
        raise DatabaseUnavailableError("test failure")

    monkeypatch.setattr(repo, "complete_request", broken)
    q = item()
    with pytest.raises(DatabaseUnavailableError):
        app.submit("owner", cid, q)
    assert app.submit("owner", cid, q, retry=True).state == "RUNNING"
    assert service.calls == 1


def test_two_workers_use_one_generation(setup):
    repo, service, app, cid = setup
    entered, release = Event(), Event()
    original = service.reply

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    service.reply = blocked
    other_worker = StoredChatService(repo, service_factory=lambda: service)
    q = item()
    with ThreadPoolExecutor(max_workers=2) as pool:
        task = pool.submit(app.submit, "owner", cid, q)
        try:
            assert entered.wait(5)
            assert other_worker.submit("owner", cid, q).state == "RUNNING"
        finally:
            release.set()
        assert task.result(timeout=5).state == "COMPLETED"
    assert service.calls == 1


def test_explicit_failed_response_is_saved_and_replayed(setup):
    _, service, app, cid = setup

    def failed(question, *, context, timeout_s):
        service.calls += 1
        return ChatResponse(
            request_id=question.request_id,
            intent="MANUAL",
            status="FAILED",
            applied_conditions={},
            message="일시 장애",
            failure=dict(code="TIMEOUT", retryable=True),
            generated_at=datetime.now(UTC),
        )

    service.reply = failed
    q = item()
    saved = app.submit("owner", cid, q)
    assert saved.state == "COMPLETED" and saved.response.status == "FAILED"
    app.submit("owner", cid, q, retry=True)
    assert service.calls == 1


def test_missing_faq_never_falls_back_to_llm(setup):
    repo, service, _, cid = setup
    catalog = load_faq_catalog()
    app = StoredChatService(repo, faq=catalog, service_factory=lambda: service)
    q = ChatSubmission(
        request_id=uuid4(),
        kind="FAQ",
        faq_id="NO-SUCH-FAQ",
    )
    result = app.submit("owner", cid, q)
    assert result.state == "FAILED" and service.calls == 0


def test_saved_history_is_read_without_service_dependency(setup):
    repo, service, app, cid = setup
    q = item()
    original = app.submit("owner", cid, q).response

    def unavailable():
        raise AssertionError("과거 대화 조회는 모델을 만들면 안 됨")

    app._service_factory = unavailable
    assert app.submit("owner", cid, q).response == original
    assert repo.get_request("owner", cid, q.request_id).response == original
    assert repo.get_conversation("owner", cid).messages[1].response == original
    assert service.calls == 1


def test_separate_conversations_use_independent_services_concurrently(setup):
    repo, _, _, first_id = setup
    second_id = repo.create_conversation("owner", mode="CHAT").conversation_id
    entered = Barrier(2)
    instances = []

    class DedicatedService(FakeService):
        def reply(self, *args, **kwargs):
            entered.wait(timeout=5)
            return super().reply(*args, **kwargs)

    def factory():
        service = DedicatedService()
        instances.append(service)
        return service

    app = StoredChatService(repo, service_factory=factory)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(app.submit, "owner", first_id, item())
        second = pool.submit(app.submit, "owner", second_id, item())
        assert first.result(timeout=10).state == "COMPLETED"
        assert second.result(timeout=10).state == "COMPLETED"
    assert len(instances) == 2 and all(service.calls == 1 for service in instances)


def test_chat_run_is_traced_under_conversation_session(setup):
    from weeing_weeing.agent import tracing

    repo, service, app, cid = setup
    seen = []
    original = service.reply

    def reply(question, **kwargs):
        seen.append(tracing._session.get())
        return original(question, **kwargs)

    service.reply = reply
    app.submit("owner", cid, item())
    assert seen == [str(cid)]
    assert tracing._session.get() is None  # 실행이 끝나면 원래대로
