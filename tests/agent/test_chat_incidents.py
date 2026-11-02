"""실제 임시 DB→도구 루프→인용·검토→응답. Claude·사용자 DB는 호출하지 않는다."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from weeing_weeing.agent.interface import get_chat_service
from weeing_weeing.api.chat_knowledge import DatabaseChatKnowledge
from weeing_weeing.contracts import ChatContext, ChatQuestion, Incident
from weeing_weeing.db.interface import open_incidents

NOW = datetime(2026, 11, 2, 5, tzinfo=UTC)


class Client:
    provider = model_name = "fake"
    last_usage = None

    def __init__(self, query):
        self.query = query
        self.calls = 0
        self.evidence = None
        self.review = None

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            name, data = "query_incidents", self.query
        else:
            tool = kwargs["messages"][-1]["content"][0]
            assert not tool["is_error"], tool["content"]
            self.evidence = json.loads(tool["content"])
            name = "submit_answer"
            data = dict(
                intent="INCIDENT",
                status="OK",
                message="안내",
                parts=[
                    dict(
                        kind="INCIDENT",
                        text="DB에 저장된 알림 현황입니다.",
                        source_ids=[self.evidence["source"]["source_id"]],
                    )
                ],
                clarification_questions=[],
            )
        block = SimpleNamespace(type="tool_use", id=str(uuid4()), name=name, input=data)
        return SimpleNamespace(content=[block])

    def generate_json(self, system, user, **kwargs):
        self.review = json.loads(user)
        return '{"verdict":"SUPPORTED","unsupported_parts":[]}'


@pytest.fixture
def knowledge(tmp_path):
    repo = open_incidents(f"sqlite:///{tmp_path / 'incidents.db'}")
    repo.save_incident(
        Incident(
            incident_id="active",
            process_id="P1",
            asset_id="A1",
            codes=["BTT2-M10"],
            severity="Warning",
            first_detected_at=NOW,
            last_detected_at=NOW,
            evidence=[
                dict(
                    field="motor_housing_temp_c",
                    value=86,
                    unit="℃",
                    threshold=">85℃, 10초",
                    observed="10초",
                )
            ],
        )
    )
    repo.save_incident(
        Incident(
            incident_id="recovered",
            process_id="P1",
            asset_id="A1",
            codes=["BTT2-P03"],
            severity="Error",
            status="RECOVERED",
            first_detected_at=NOW - timedelta(hours=2),
            last_detected_at=NOW - timedelta(hours=1),
            recovered_at=NOW,
        )
    )
    yield DatabaseChatKnowledge(None, None, None, repo)
    repo._engine.dispose()


@pytest.mark.parametrize("state", ["ACTIVE", "RECOVERED"])
def test_real_db_tool_result_reaches_answer_and_grounding(knowledge, state):
    client = Client(dict(state=state))
    response = get_chat_service(knowledge, client=client).reply(
        ChatQuestion(
            request_id=uuid4(),
            question="지금 알림" if state == "ACTIVE" else "사라진 알림",
            conditions=dict(asset_id="A1"),
        ),
        context=ChatContext(),
        timeout_s=10,
    )
    assert response.status == "OK" and response.intent == "INCIDENT"
    assert response.sources[0].query.asset_id == "A1"
    assert client.calls == 2
    if state == "ACTIVE":
        fact = client.evidence["incidents"][0]["evidence"][0]
        assert fact["value"] == 86 and fact["threshold"] == ">85℃, 10초"
        assert response.sources[0].warning_count == 1
    else:
        assert (
            "다른 알림" in response.parts[0].text and "시간대" in response.parts[0].text
        )
        assert response.sources[0].incident_ids == ["recovered"]
    assert client.review["evidence"]


def test_empty_db_result_is_citable_zero_not_failure(knowledge):
    client = Client(dict(asset_id="missing"))
    response = get_chat_service(knowledge, client=client).reply(
        ChatQuestion(request_id=uuid4(), question="현재 알림"),
        context=ChatContext(),
        timeout_s=10,
    )
    assert response.status == "OK" and response.sources[0].total == 0


def test_db_failure_is_not_reported_as_no_alerts(knowledge, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(knowledge.incidents, "query_incidents", fail)
    response = get_chat_service(knowledge, client=Client({})).reply(
        ChatQuestion(request_id=uuid4(), question="현재 알림"),
        context=ChatContext(),
        timeout_s=10,
    )
    assert response.status == "FAILED" and response.failure.code == "SEARCH_UNAVAILABLE"


def test_incident_only_query_does_not_open_rag(knowledge, monkeypatch):
    from weeing_weeing.api import chat_knowledge
    from weeing_weeing.contracts.chat import ChatIncidentQuery

    def unavailable():
        raise AssertionError("RAG must not be opened for incident lookup")

    monkeypatch.setattr(chat_knowledge, "get_retriever", unavailable)
    assert knowledge.query_incidents(ChatIncidentQuery(), timeout_s=1).source.total == 1


def test_selected_date_filters_recovery_in_korean_time(knowledge):
    client = Client(dict(state="RECOVERED"))
    response = get_chat_service(knowledge, client=client).reply(
        ChatQuestion(
            request_id=uuid4(),
            question="오늘 회복된 경고",
            conditions=dict(date_from="2026-11-02", date_to="2026-11-02"),
        ),
        context=ChatContext(),
        timeout_s=10,
    )
    assert response.status == "OK"
    query = response.sources[0].query
    assert query.time_from.isoformat() == "2026-11-02T00:00:00+09:00"
    assert query.time_to.isoformat() == "2026-11-02T23:59:59.999999+09:00"
    assert not client.evidence["latest_recovered_only"]
    assert "다른 알림" not in response.parts[0].text
