"""실제 Bearer 인증·임시 DB·가짜 생성기로 FAQ 버튼과 대화 HTTP 흐름을 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from weeing_weeing.agent.interface import load_faq_catalog
from weeing_weeing.agent.tracing import LangfuseTracer
from weeing_weeing.api import chat
from weeing_weeing.api.app import app
from weeing_weeing.api.chat_storage import StoredChatService
from weeing_weeing.contracts import ChatResponse, Role, UserAccount
from weeing_weeing.db import interface as db


class FakeService:
    def __init__(self):
        self.calls = 0
        self.questions = []
        self.entered = Event()
        self.release = Event()
        self.blocked = False
        self.fail = False
        self.failed_response = False

    def reply(self, question, *, context, timeout_s):
        self.calls += 1
        self.questions.append(question)
        self.entered.set()
        if self.blocked:
            assert self.release.wait(5)
        if self.fail:
            raise RuntimeError("private-provider-payload")
        return ChatResponse(
            request_id=question.request_id,
            intent="MANUAL",
            status="FAILED" if self.failed_response else "INSUFFICIENT_EVIDENCE",
            applied_conditions=question.conditions,
            message="모의 응답",
            generated_at=datetime.now(UTC),
            failure=dict(code="TIMEOUT", retryable=True)
            if self.failed_response
            else None,
        )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from weeing_weeing.db import users as users_module

    monkeypatch.setattr(users_module, "SCRYPT_N", 2**10)
    url = f"sqlite:///{tmp_path / 'http.db'}"
    users = db.open_users(url)
    repo = db.open_chats(url)
    for no in ["owner", "other", "admin"]:
        users.create_user(
            UserAccount(
                employee_no=no, name=no, role=Role.CONTROL, is_admin=no == "admin"
            ),
            "test-password",
        )
    monkeypatch.setattr(db, "get_users", lambda: users)
    monkeypatch.setattr(db, "get_chats", lambda: repo)
    catalog = load_faq_catalog()
    fake = FakeService()
    stored = StoredChatService(repo, faq=catalog, service_factory=lambda: fake)
    app.dependency_overrides[chat.faq_catalog] = lambda: catalog
    app.dependency_overrides[chat.stored_chat] = lambda: stored
    client = TestClient(app)
    headers = {}
    for no in ["owner", "other", "admin"]:
        result = client.post(
            "/auth/login", json=dict(employee_no=no, password="test-password")
        )
        assert result.status_code == 200
        headers[no] = {"Authorization": "Bearer " + result.json()["access_token"]}
    yield client, headers, repo, catalog, fake
    app.dependency_overrides.pop(chat.faq_catalog, None)
    app.dependency_overrides.pop(chat.stored_chat, None)
    repo._engine.dispose()
    users._engine.dispose()


def create(client, headers, **kwargs):
    result = client.post("/chat/conversations", headers=headers, json=kwargs)
    assert result.status_code == 201, result.text
    assert result.headers["cache-control"] == "no-store"
    return "/chat/conversations/" + result.json()["conversation_id"]


def start(client, headers, path):
    result = client.patch(path, headers=headers, json={"mode": "CHAT"})
    assert result.status_code == 200


def test_faq_button_flow_persists_and_replays_without_llm(setup):
    client, headers, repo, catalog, fake = setup
    owner = headers["owner"]
    topics = client.get("/chat/faq/topics", headers=owner)
    assert topics.status_code == 200 and topics.json()
    questions = client.get(
        f"/chat/faq/topics/{topics.json()[0]['topic_id']}/questions", headers=owner
    )
    question = questions.json()[0]
    assert "faq_version" not in question
    path = create(client, owner)
    assert client.get(path, headers=owner).json()["conversation"]["mode"] == "FAQ"
    body = dict(
        request_id=str(uuid4()),
        faq_id=question["faq_id"],
    )
    result = client.post(path + "/faq-selections", headers=owner, json=body)
    assert result.status_code == 200 and result.json()["response"]["intent"] == "FAQ"
    assert result.json()["state"] == "COMPLETED" and fake.calls == 0
    replay = client.post(path + "/faq-selections", headers=owner, json=body)
    assert replay.json() == result.json()
    assert client.get(result.headers["location"], headers=owner).json() == result.json()
    page = client.get(path, headers=owner).json()
    assert [m["role"] for m in page["messages"]] == ["user", "assistant"]
    assert page["messages"][0]["content"] == question["question"]
    assert "execution_token" not in result.text and "owner_id" not in result.text
    assert "usage" not in result.json()


def test_chat_start_conditions_and_response_json(setup):
    client, headers, _, _, fake = setup
    owner = headers["owner"]
    path = create(client, owner, conditions={"asset_id": "BLDC-001"})
    body = dict(request_id=str(uuid4()), question="센서 점검 방법")
    assert client.post(path + "/messages", headers=owner, json=body).status_code == 409
    start(client, owner, path)
    result = client.post(path + "/messages", headers=owner, json=body)
    assert (
        result.status_code == 200
        and result.json()["response"]["message"] == "모의 응답"
    )
    assert result.json()["conditions"]["asset_id"] == "BLDC-001"
    assert fake.questions[0].conditions.asset_id == "BLDC-001"
    assert (
        client.post(path + "/messages", headers=owner, json=body).json()
        == result.json()
    )
    assert fake.calls == 1
    changed = body | {"question": "바꾼 질문"}
    assert (
        client.post(path + "/messages", headers=owner, json=changed).status_code == 409
    )


def test_chat_usage_is_recorded_as_the_logged_in_user(setup, monkeypatch):
    """서버 하나를 여럿이 써도 Langfuse user_id는 LLM_USER가 아니라 로그인 계정 이름이다."""
    client, headers, _, _, fake = setup
    users = []

    class Client:
        @contextmanager
        def start_as_current_observation(self, **kwargs):
            yield None

    @contextmanager
    def propagate(**attributes):
        users.append(attributes["user_id"])
        yield

    tracer = LangfuseTracer(
        Client(), user_id="ec2", entrypoint="api", propagate=propagate
    )
    reply = fake.reply

    def traced(question, **kwargs):
        with tracer.observe("chat-assistant"):
            return reply(question, **kwargs)

    monkeypatch.setattr(fake, "reply", traced)
    path = create(client, headers["owner"])
    start(client, headers["owner"], path)
    body = dict(request_id=str(uuid4()), question="센서 점검")
    result = client.post(path + "/messages", headers=headers["owner"], json=body)
    assert result.status_code == 200
    body = dict(request_id=str(uuid4()), question="센서 점검 2")
    result = client.post(path + "/messages/stream", headers=headers["owner"], json=body)
    assert stream_events(result.text)[-1]["event"] == "done"
    with tracer.observe("incident-analysis"):  # 요청 밖은 LLM_USER
        pass
    assert users == ["owner", "owner", "ec2"]


@pytest.mark.parametrize("actor", ["other", "admin"])
def test_all_private_endpoints_reject_other_users_and_admin(setup, actor):
    client, headers, _, catalog, fake = setup
    owner, stranger = headers["owner"], headers[actor]
    path = create(client, owner)
    start(client, owner, path)
    request_id = str(uuid4())
    body = dict(request_id=request_id, question="센서 질문")
    assert client.post(path + "/messages", headers=owner, json=body).status_code == 200
    faq = catalog.list_questions(catalog.list_topics()[0].topic_id)[0]
    attempts = [
        client.get(path, headers=stranger),
        client.get(path + "/requests/" + request_id, headers=stranger),
        client.patch(path, headers=stranger, json={"title": "타인 변경"}),
        client.delete(path, headers=stranger),
        client.post(path + "/messages", headers=stranger, json=body),
        client.post(
            path + "/faq-selections",
            headers=stranger,
            json=dict(request_id=str(uuid4()), faq_id=faq.faq_id),
        ),
    ]
    for result in attempts:
        assert result.status_code == 404, result.text
        assert result.json() == {"detail": "요청한 항목을 찾을 수 없습니다."}
    assert client.get("/chat/conversations", headers=stranger).json() == []
    assert fake.calls == 1
    missing = client.get("/chat/conversations/" + str(uuid4()), headers=stranger)
    assert missing.json() == attempts[0].json()


def test_all_chat_endpoints_require_login(setup):
    client, headers, _, catalog, _ = setup
    path = create(client, headers["owner"])
    faq = catalog.list_questions(catalog.list_topics()[0].topic_id)[0]
    requests = [
        client.get("/chat/faq/topics"),
        client.get(f"/chat/faq/topics/{faq.topic_id}/questions"),
        client.post("/chat/conversations", json={}),
        client.get("/chat/conversations"),
        client.get(path),
        client.patch(path, json={"mode": "CHAT"}),
        client.delete(path),
        client.get(path + "/requests/" + str(uuid4())),
        client.post(
            path + "/messages", json=dict(request_id=str(uuid4()), question="질문")
        ),
        client.post(
            path + "/faq-selections",
            json=dict(request_id=str(uuid4()), faq_id=faq.faq_id),
        ),
    ]
    for result in requests:
        assert (
            result.status_code == 401 and result.headers["www-authenticate"] == "Bearer"
        )
    assert (
        client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
    )


def test_validation_rejects_identity_context_and_wrong_request_kind(setup):
    client, headers, _, catalog, fake = setup
    owner = headers["owner"]
    path = create(client, owner)
    faq = catalog.list_questions(catalog.list_topics()[0].topic_id)[0]
    for field in ["owner_id", "actor_id", "mode"]:
        assert (
            client.post(
                "/chat/conversations", headers=owner, json={field: "other"}
            ).status_code
            == 422
        )
    for field in ["owner_id", "actor_id", "context", "intent", "kind"]:
        body = dict(request_id=str(uuid4()), question="질문") | {field: "other"}
        assert (
            client.post(path + "/messages", headers=owner, json=body).status_code == 422
        )
    assert (
        client.post(
            path + "/faq-selections",
            headers=owner,
            json=dict(
                request_id=str(uuid4()),
                faq_id=faq.faq_id,
                question="임의 질문",
            ),
        ).status_code
        == 422
    )
    for body in [
        dict(mode=None),
        dict(mode="WRONG"),
        dict(title=" "),
        dict(conditions=dict(date_from="2026-10-10", date_to="2026-01-01")),
    ]:
        assert client.patch(path, headers=owner, json=body).status_code == 422
    assert client.get(path + "?limit=201", headers=owner).status_code == 422
    assert fake.calls == 0


def test_paging_list_update_and_delete(setup):
    client, headers, _, _, _ = setup
    owner = headers["owner"]
    path = create(client, owner)
    start(client, owner, path)
    client.post(
        path + "/messages",
        headers=owner,
        json=dict(request_id=str(uuid4()), question="질문"),
    )
    first = client.get(path + "?limit=1", headers=owner).json()
    assert first["has_more"] and first["messages"][0]["sequence"] == 1
    second = client.get(path + "?after_sequence=1&limit=1", headers=owner).json()
    assert not second["has_more"] and second["messages"][0]["role"] == "assistant"
    assert len(client.get("/chat/conversations?limit=1", headers=owner).json()) == 1
    assert client.get("/chat/conversations?offset=1", headers=owner).json() == []
    assert (
        client.patch(path, headers=owner, json={"title": "내 대화"}).json()["title"]
        == "내 대화"
    )
    assert client.delete(path, headers=owner).status_code == 204
    assert client.get(path, headers=owner).status_code == 404


def test_duplicate_during_execution_returns_202_and_can_be_polled(setup):
    client, headers, _, _, fake = setup
    owner = headers["owner"]
    path = create(client, owner)
    start(client, owner, path)
    fake.blocked = True
    body = dict(request_id=str(uuid4()), question="센서 점검")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, path + "/messages", headers=owner, json=body)
        try:
            assert fake.entered.wait(5)
            duplicate = client.post(path + "/messages", headers=owner, json=body)
            assert duplicate.status_code == 202
            assert (
                duplicate.json()["response"] is None
                and duplicate.json()["state"] == "RUNNING"
            )
            assert duplicate.headers["retry-after"] == "1"
            assert (
                client.get(duplicate.headers["location"], headers=owner).status_code
                == 202
            )
            assert (
                client.patch(path, headers=owner, json={"mode": "FAQ"}).status_code
                == 409
            )
        finally:
            fake.release.set()
        assert first.result(timeout=5).status_code == 200
    finished = client.get(duplicate.headers["location"], headers=owner)
    assert (
        finished.status_code == 200
        and finished.json()["response"] is not None
        and fake.calls == 1
    )


def test_unknown_result_is_409_without_automatic_retry(setup):
    client, headers, _, _, fake = setup
    path = create(client, headers["owner"])
    start(client, headers["owner"], path)
    fake.fail = True
    body = dict(request_id=str(uuid4()), question="질문")
    result = client.post(path + "/messages", headers=headers["owner"], json=body)
    assert result.status_code == 409 and result.json()["state"] == "UNKNOWN"
    assert not result.json()["retry_allowed"] and "private-provider" not in result.text
    assert (
        client.post(
            path + "/messages?retry=true", headers=headers["owner"], json=body
        ).status_code
        == 409
    )
    assert fake.calls == 1


def test_faq_selection_errors_are_preserved_and_do_not_call_llm(setup):
    client, headers, _, catalog, fake = setup
    owner = headers["owner"]
    path = create(client, owner)
    for faq_id, status, error in [("NO-SUCH-FAQ", 404, "FAQ_NOT_FOUND")]:
        body = dict(request_id=str(uuid4()), faq_id=faq_id)
        result = client.post(path + "/faq-selections", headers=owner, json=body)
        assert result.status_code == status and result.json()["error_code"] == error
        assert result.json()["state"] == "FAILED" and not result.json()["retry_allowed"]
        replay = client.post(
            path + "/faq-selections?retry=true", headers=owner, json=body
        )
        assert replay.json() == result.json() and replay.status_code == status
    assert (
        client.get(
            "/chat/faq/topics/NO-SUCH-TOPIC/questions", headers=owner
        ).status_code
        == 404
    )
    assert fake.calls == 0


def test_db_outage_is_safe_503(setup, monkeypatch):
    client, headers, _, _, _ = setup

    def unavailable():
        raise db.DatabaseUnavailableError("private-db-credentials")

    monkeypatch.setattr(db, "get_chats", unavailable)
    result = client.get("/chat/conversations", headers=headers["owner"])
    assert result.status_code == 503 and "private-db" not in result.text


def test_preparation_failure_503_requires_explicit_retry(setup):
    client, headers, _, _, fake = setup
    stored = app.dependency_overrides[chat.stored_chat]()
    original = stored._service_factory

    def unavailable():
        raise RuntimeError("private-settings")

    stored._service_factory = unavailable
    path = create(client, headers["owner"])
    start(client, headers["owner"], path)
    body = dict(request_id=str(uuid4()), question="질문")
    failed = client.post(path + "/messages", headers=headers["owner"], json=body)
    assert failed.status_code == 503 and failed.json()["retry_allowed"]
    stored._service_factory = original
    assert (
        client.post(path + "/messages", headers=headers["owner"], json=body).status_code
        == 503
    )
    assert (
        client.post(
            path + "/messages?retry=true", headers=headers["owner"], json=body
        ).status_code
        == 200
    )
    assert fake.calls == 1


def test_completed_failure_response_is_still_saved_and_replayed(setup):
    client, headers, _, _, fake = setup
    path = create(client, headers["owner"])
    start(client, headers["owner"], path)
    fake.failed_response = True
    body = dict(request_id=str(uuid4()), question="질문")
    result = client.post(path + "/messages", headers=headers["owner"], json=body)
    assert result.status_code == 200 and result.json()["state"] == "COMPLETED"
    assert result.json()["response"]["status"] == "FAILED"
    assert (
        client.post(
            path + "/messages?retry=true", headers=headers["owner"], json=body
        ).json()
        == result.json()
    )
    assert fake.calls == 1


def test_production_wiring_faq_does_not_build_a_generation_service(setup, monkeypatch):
    client, headers, _, catalog, _ = setup
    app.dependency_overrides.pop(chat.stored_chat)

    def forbidden(*args, **kwargs):
        raise AssertionError("FAQ 선택에 생성 서비스 필요 없음")

    monkeypatch.setattr(chat, "get_chat_service", forbidden)
    faq = catalog.list_questions(catalog.list_topics()[0].topic_id)[0]
    path = create(client, headers["owner"])
    result = client.post(
        path + "/faq-selections",
        headers=headers["owner"],
        json=dict(request_id=str(uuid4()), faq_id=faq.faq_id),
    )
    assert result.status_code == 200 and result.json()["response"]["intent"] == "FAQ"


def test_catalog_outage_is_503_without_raw_exception(setup, monkeypatch):
    from weeing_weeing.agent.interface import FaqCatalogError

    client, headers, _, _, fake = setup
    app.dependency_overrides.pop(chat.faq_catalog)

    def unavailable():
        raise FaqCatalogError("private-file-path")

    monkeypatch.setattr(chat, "_faq_snapshot", unavailable)
    result = client.get("/chat/faq/topics", headers=headers["owner"])
    assert result.status_code == 503 and "private-file" not in result.text
    assert client.get("/health").status_code == 200 and fake.calls == 0


def test_openapi_documents_authenticated_routes_and_pending_response(setup):
    client, _, _, _, _ = setup
    schema = client.get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        if path.startswith("/chat/"):
            assert all(operation.get("security") for operation in methods.values())
    responses = schema["paths"]["/chat/conversations/{conversation_id}/messages"][
        "post"
    ]["responses"]
    assert "200" in responses and "202" in responses and "409" in responses


@pytest.mark.parametrize(
    "field,value",
    [
        ("faq_version", "1"),
        ("reviewed_at", "2026-01-01"),
        ("references", ["docs/AUTH.md"]),
    ],
)
def test_faq_http_does_not_require_or_accept_retired_metadata(setup, field, value):
    client, headers, _, catalog, fake = setup
    faq = catalog.list_questions(catalog.list_topics()[0].topic_id)[0]
    path = create(client, headers["owner"])
    body = dict(request_id=str(uuid4()), faq_id=faq.faq_id)
    assert (
        client.post(
            path + "/faq-selections",
            headers=headers["owner"],
            json=body | {field: value},
        ).status_code
        == 422
    )
    result = client.post(path + "/faq-selections", headers=headers["owner"], json=body)
    assert result.status_code == 200 and result.json()["response"]["intent"] == "FAQ"
    assert all(field not in source for source in result.json()["response"]["sources"])
    assert fake.calls == 0


@pytest.mark.parametrize("kind", ["FAQ", "CHAT"])
def test_production_replay_needs_no_catalog_or_generation_dependency(
    setup, monkeypatch, kind
):
    client, headers, _, catalog, fake = setup
    owner = headers["owner"]
    path = create(client, owner)
    if kind == "FAQ":
        faq = catalog.list_questions(catalog.list_topics()[0].topic_id)[0]
        endpoint = path + "/faq-selections"
        body = dict(request_id=str(uuid4()), faq_id=faq.faq_id)
    else:
        start(client, owner, path)
        endpoint = path + "/messages"
        body = dict(request_id=str(uuid4()), question="저장된 질문")
    saved = client.post(endpoint, headers=owner, json=body)
    assert saved.status_code == 200
    calls = fake.calls
    app.dependency_overrides.pop(chat.stored_chat)

    def unavailable(*args, **kwargs):
        raise AssertionError("중복 요청에는 카탈로그·생성 의존성 접근 금지")

    monkeypatch.setattr(chat, "_faq_snapshot", unavailable)
    monkeypatch.setattr(chat, "get_chat_service", unavailable)
    replay = client.post(endpoint, headers=owner, json=body)
    assert replay.status_code == 200 and replay.json() == saved.json()
    assert fake.calls == calls


def stream_events(text):
    import json

    return [
        json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")
    ]


def test_stream_sends_saved_markdown_and_duplicate_does_not_execute(setup, monkeypatch):
    client, headers, repo, _, fake = setup
    path = create(client, headers["owner"])
    start(client, headers["owner"], path)
    markdown = (
        "## 점검\n\n**센서 상태**를 확인합니다.\n\n" + "센서 점검 근거입니다. " * 80
    )

    def answer(question, *, context, timeout_s):
        fake.calls += 1
        return ChatResponse(
            request_id=question.request_id,
            intent="MANUAL",
            status="OK",
            applied_conditions=question.conditions,
            message="근거 안내",
            parts=[dict(kind="MANUAL", text=markdown, source_ids=["doc:1"])],
            sources=[
                dict(
                    kind="DOCUMENT",
                    source_id="doc:1",
                    title="매뉴얼",
                    doc_id="MAN",
                    doc_version="1",
                    page=1,
                )
            ],
            generated_at=datetime.now(UTC),
        )

    monkeypatch.setattr(fake, "reply", answer)
    body = dict(request_id=str(uuid4()), question="센서 점검")
    result = client.post(path + "/messages/stream", headers=headers["owner"], json=body)
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("text/event-stream")
    assert result.headers["cache-control"] == "no-store"
    events = stream_events(result.text)
    assert events[0]["phase"] == "accepted"
    assert events[-1]["event"] == "done"
    stored = events[-1]["request"]
    assert stored["state"] == "COMPLETED"
    assert (
        "".join(e["text"] for e in events if e["event"] == "delta")
        == stored["response"]["parts"][0]["text"]
    )
    assert fake.calls == 1
    replay = stream_events(
        client.post(path + "/messages/stream", headers=headers["owner"], json=body).text
    )
    assert replay[-1]["request"]["response"] == stored["response"]
    assert fake.calls == 1
    assert (
        client.get(path, headers=headers["owner"]).json()["messages"][-1]["response"]
        == stored["response"]
    )
    assert (
        client.post(
            path + "/messages/stream", headers=headers["other"], json=body
        ).status_code
        == 404
    )
    assert client.post(path + "/messages/stream", json=body).status_code == 401


def test_non_ok_stream_has_no_answer_delta_and_conflict_is_sanitized(setup):
    client, headers, _, _, fake = setup
    path = create(client, headers["owner"])
    start(client, headers["owner"], path)
    body = dict(request_id=str(uuid4()), question="질문")
    result = client.post(path + "/messages/stream", headers=headers["owner"], json=body)
    events = stream_events(result.text)
    assert not any(e["event"] == "delta" for e in events)
    assert events[-1]["request"]["response"]["status"] == "INSUFFICIENT_EVIDENCE"
    changed = client.post(
        path + "/messages/stream",
        headers=headers["owner"],
        json=body | {"question": "다른 질문"},
    )
    assert stream_events(changed.text)[-1]["status_code"] == 409
    assert stream_events(changed.text)[-1]["request_reserved"] is False
    assert fake.calls == 1


def test_message_model_selection_reaches_service_factory(setup):
    client, headers, _, _, fake = setup
    stored = app.dependency_overrides[chat.stored_chat]()
    seen = []

    def factory(model=None):
        seen.append(model)
        return fake

    stored._service_factory = factory
    owner = headers["owner"]
    path = create(client, owner)
    start(client, owner, path)

    def send(**extra):
        body = dict(request_id=str(uuid4()), question="질문", **extra)
        return client.post(path + "/messages", headers=owner, json=body)

    assert send(model="claude-opus-5-5").status_code == 200
    assert send().status_code == 200
    assert send(model="gpt-4").status_code == 422
    assert seen == ["claude-opus-5-5", None]

    request_id = str(uuid4())
    body = {
        "request_id": request_id,
        "question": "중복 질문",
        "model": "claude-opus-5-5",
    }
    first = client.post(path + "/messages", headers=owner, json=body)
    assert first.status_code == 200
    assert first.json()["submission"]["model"] == "claude-opus-5-5"
    assert (
        client.post(
            path + "/messages",
            headers=owner,
            json={**body, "model": "claude-sonnet-5-5"},
        ).status_code
        == 409
    )
