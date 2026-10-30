import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from weeing_weeing.agent.chat import ToolChatService
from weeing_weeing.agent.interface import (
    InvalidChatQueryError,
    LlmTimeoutError,
    get_chat_service,
    load_faq_catalog,
)
from weeing_weeing.contracts import ChatContext, ChatQuestion, ChatSearchConditions
from weeing_weeing.contracts.chat_tools import ChatSearchHit


def call(name, data):
    return SimpleNamespace(type="tool_use", id=str(uuid4()), name=name, input=data)


def reply(*blocks):
    return SimpleNamespace(content=list(blocks))


def search(kind="MANUAL", **data):
    return call("search_knowledge", dict(query="입구 센서 점검", kind=kind) | data)


def submit(
    status="OK",
    intent="MANUAL",
    ids=("manual:1",),
    text="센서 상태를 확인합니다.",
    **extra,
):
    return call(
        "submit_answer",
        dict(
            intent=intent,
            status=status,
            message="자료 안내입니다.",
            parts=[dict(kind=intent, text=text, source_ids=list(ids))]
            if status == "OK"
            else [],
            clarification_questions=["어느 설비인가요?"]
            if status == "NEEDS_CLARIFICATION"
            else [],
        )
        | extra,
    )


class FakeClient:
    provider = "fake"
    model_name = "fake"
    last_usage = None

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def generate_json(self, system, user, **kwargs):
        # 기존 도구 루프 테스트는 검토 호출을 통과시키고, 검토 자체는 별도 사례로 검증한다.
        return '{"verdict":"SUPPORTED","unsupported_parts":[]}'


def document():
    return ChatSearchHit(
        source=dict(
            kind="DOCUMENT",
            source_id="manual:1",
            title="매뉴얼",
            doc_id="MAN",
            doc_version="1",
            page=2,
        ),
        text="센서 상태를 확인한다.",
    )


class CommonKnowledge:
    def __init__(
        self, hits=None, *, searchable=True, query_error=None, search_error=None
    ):
        self.hits = [document()] if hits is None else hits
        self.searchable = searchable
        self.query_error = query_error
        self.search_error = search_error
        self.validated = []
        self.searches = []
        self.reads = []

    def validate_query(self, query, *, timeout_s):
        assert timeout_s > 0
        self.validated.append(query)
        if self.query_error:
            raise self.query_error

    def search(self, query, *, timeout_s):
        assert self.validated[-1] == query
        self.searches.append(query)
        if self.search_error:
            raise self.search_error
        return self.hits

    def is_searchable(self, source, *, timeout_s):
        self.reads.append(source)
        return self.searchable


def ask(client, knowledge=None, *, context=None, conditions=None, max_turns=6):
    service = ToolChatService(
        client, knowledge or CommonKnowledge(), load_faq_catalog(), max_turns=max_turns
    )
    question = ChatQuestion(
        request_id=uuid4(),
        question="입구 센서는 어떻게 점검하나요?",
        conditions=conditions or {},
    )
    return service.reply(question, context=context or ChatContext(), timeout_s=10)


def test_free_question_calls_tools_without_separate_classifier():
    client = FakeClient(reply(search(code="BTT2-P03")), reply(submit()))
    knowledge = CommonKnowledge()
    conditions = ChatSearchConditions(asset_id="BLDC-001", limit=2)
    result = ask(client, knowledge, conditions=conditions)
    assert result.status == "OK"
    assert result.parts[0].source_ids == ["manual:1"]
    assert result.applied_conditions == conditions
    assert knowledge.searches[0].conditions == conditions
    assert knowledge.searches[0].code == "BTT2-P03"
    assert len(knowledge.reads) == 3  # 검색 후·제출 전·근거 검토 후 재검사
    assert len(client.calls) == 2
    task = json.loads(client.calls[0]["messages"][0]["content"])
    assert task["timezone"] == "Asia/Seoul"
    assert "reference_date" in task
    names = {tool["name"] for tool in client.calls[0]["tools"]}
    assert names == {
        "search_knowledge",
        "query_history",
        "browse_faq",
        "get_faq_answer",
        "submit_answer",
    }


@pytest.mark.parametrize(
    "conditions",
    [
        {"limit": True},
        {"limit": 21},
        {"date_from": "2026-10-30", "date_to": "2026-10-01"},
    ],
)
def test_malformed_filters_never_reach_search(conditions):
    client = FakeClient(
        reply(search(conditions=conditions)), reply(submit("NEEDS_CLARIFICATION"))
    )
    knowledge = CommonKnowledge()
    result = ask(client, knowledge)
    assert result.status == "NEEDS_CLARIFICATION"
    assert not knowledge.searches and not knowledge.validated


def test_unknown_code_does_not_reach_search():
    client = FakeClient(
        reply(search(code="UNKNOWN")), reply(submit("NEEDS_CLARIFICATION"))
    )
    knowledge = CommonKnowledge()
    assert ask(client, knowledge).status == "NEEDS_CLARIFICATION"
    assert not knowledge.searches


def test_unsupported_filter_is_reasked_instead_of_silently_dropped():
    client = FakeClient(
        reply(search(conditions={"date_from": "2026-10-01"})),
        reply(submit("NEEDS_CLARIFICATION")),
    )
    knowledge = CommonKnowledge(
        query_error=InvalidChatQueryError("기간 집계는 DB 조회 필요")
    )
    assert ask(client, knowledge).status == "NEEDS_CLARIFICATION"
    assert not knowledge.searches


def test_validation_service_failure_stops_before_search():
    client = FakeClient(reply(search()))
    knowledge = CommonKnowledge(query_error=RuntimeError("private details"))
    result = ask(client, knowledge)
    assert result.failure.code == "SEARCH_UNAVAILABLE"
    assert not knowledge.searches and not result.sources
    assert "private details" not in result.model_dump_json()


def test_deleted_or_superseded_result_never_reaches_llm():
    client = FakeClient(reply(search()))
    knowledge = CommonKnowledge(searchable=False)
    result = ask(client, knowledge)
    assert result.failure.code == "SEARCH_UNAVAILABLE"
    assert len(client.calls) == 1
    assert "센서 상태를 확인한다" not in json.dumps(
        client.calls, default=str, ensure_ascii=False
    )


def test_source_state_is_checked_again_before_answer_is_exposed():
    class Superseded(CommonKnowledge):
        def is_searchable(self, source, *, timeout_s):
            self.reads.append(source)
            return len(self.reads) == 1

    result = ask(FakeClient(reply(search()), reply(submit())), Superseded())
    assert result.status == "FAILED" and result.failure.code == "SEARCH_UNAVAILABLE"
    assert not result.parts and not result.sources


def test_search_failure_is_not_insufficient_evidence_or_raw_error():
    result = ask(
        FakeClient(reply(search())),
        CommonKnowledge(search_error=RuntimeError("secret")),
    )
    assert result.failure.code == "SEARCH_UNAVAILABLE"
    assert "secret" not in result.model_dump_json()


def test_empty_results_can_return_insufficient_evidence():
    client = FakeClient(reply(search()), reply(submit("INSUFFICIENT_EVIDENCE")))
    result = ask(client, CommonKnowledge(hits=[]))
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert not result.parts and not result.sources


def test_oversized_evidence_batch_is_not_sent_to_llm():
    hits = []
    for i in range(5):
        hit = document()
        hit.source.source_id = f"manual:{i}"
        hit.text = "근거" * 4000
        hits.append(hit)
    client = FakeClient(reply(search()), reply(submit("NEEDS_CLARIFICATION")))
    result = ask(client, CommonKnowledge(hits=hits))
    assert result.status == "NEEDS_CLARIFICATION"
    assert not result.sources
    assert "근거" * 100 not in json.dumps(client.calls, default=str, ensure_ascii=False)


def test_fabricated_citation_gets_a_correction_turn():
    client = FakeClient(
        reply(submit(ids=("invented",))), reply(submit("INSUFFICIENT_EVIDENCE"))
    )
    result = ask(client)
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert len(client.calls) == 2


def test_repeated_invalid_output_finishes_as_failure():
    client = FakeClient(reply(submit(ids=("invented",))))
    result = ask(client, max_turns=1)
    assert result.failure.code == "INVALID_RESPONSE"


def test_provider_timeout_is_distinct():
    result = ask(FakeClient(LlmTimeoutError("provider secret")))
    assert result.failure.code == "TIMEOUT" and result.failure.retryable
    assert "provider secret" not in result.model_dump_json()


def test_out_of_scope_can_finish_without_search():
    knowledge = CommonKnowledge()
    result = ask(FakeClient(reply(submit("OUT_OF_SCOPE", "OUT_OF_SCOPE"))), knowledge)
    assert result.status == "OUT_OF_SCOPE"
    assert not knowledge.searches


def test_synthetic_case_must_be_labelled_and_source_is_server_supplied():
    hit = ChatSearchHit(
        source=dict(
            kind="REPORT",
            source_id="report:1",
            title="가상 사례",
            report_id="RPT-1",
            report_version=1,
            synthetic=True,
        ),
        text="센서 정렬 확인",
    )
    client = FakeClient(
        reply(search("MAINTENANCE_HISTORY")),
        reply(submit(intent="MAINTENANCE_HISTORY", ids=("report:1",))),
        reply(
            submit(
                intent="MAINTENANCE_HISTORY",
                ids=("report:1",),
                text="가상 사례에서는 센서 정렬을 확인했습니다.",
            )
        ),
    )
    result = ask(client, CommonKnowledge(hits=[hit]))
    assert result.status == "OK" and result.sources[0].synthetic is True
    assert len(client.calls) == 3


def test_faq_tool_reuses_catalog_without_retrieving_documents():
    knowledge = CommonKnowledge()
    faq = load_faq_catalog().get_answer("FAQ-REPORT-001")
    client = FakeClient(
        reply(call("browse_faq", {"topic_id": "reports"})),
        reply(
            call(
                "get_faq_answer",
                {"faq_id": faq.source.faq_id, "faq_version": faq.source.faq_version},
            )
        ),
        reply(submit(intent="FAQ", ids=(faq.source.source_id,), text=faq.answer)),
    )
    result = ask(client, knowledge)
    assert result.status == "OK" and result.intent == "FAQ"
    assert not knowledge.searches


def test_factory_requires_explicit_knowledge_and_preserves_validated_context():
    client = FakeClient(reply(submit("NEEDS_CLARIFICATION")))
    service = get_chat_service(CommonKnowledge(), client=client)
    context = ChatContext(
        recent_turns=[dict(role="user", content="BLDC-001을 보고 있어요")]
    )
    result = service.reply(
        ChatQuestion(request_id=uuid4(), question="지난달은요?"),
        context=context,
        timeout_s=10,
    )
    assert result.status == "NEEDS_CLARIFICATION"
    task = json.loads(client.calls[0]["messages"][0]["content"])
    assert task["recent_turns"] == [dict(role="user", content="BLDC-001을 보고 있어요")]


def test_empty_followup_search_cannot_unlock_previous_conditions():
    class Knowledge(CommonKnowledge):
        def search(self, query, *, timeout_s):
            self.searches.append(query)
            return [] if query.query == "empty" else self.hits

    knowledge = Knowledge()
    client = FakeClient(
        reply(search(conditions={"asset_id": "A1"})),
        reply(search(query="empty", conditions={"asset_id": "A1"})),
        reply(search(conditions={"asset_id": "A2"})),
        reply(submit()),
    )
    result = ask(client, knowledge)
    assert result.status == "OK"
    assert result.applied_conditions.asset_id == "A1"
    assert [query.conditions.asset_id for query in knowledge.searches] == ["A1", "A1"]
    assert any(
        block.get("is_error")
        for message in client.calls[3]["messages"]
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
    )


def test_model_cannot_override_user_selected_conditions():
    knowledge = CommonKnowledge()
    client = FakeClient(
        reply(search(conditions={"asset_id": "A2"})),
        reply(submit("NEEDS_CLARIFICATION")),
    )
    result = ask(client, knowledge, conditions=ChatSearchConditions(asset_id="A1"))
    assert result.status == "NEEDS_CLARIFICATION"
    assert not knowledge.searches


def test_history_max_limit_reserves_room_for_count_source():
    from weeing_weeing.contracts.chat_tools import ChatHistoryResult

    class Knowledge(CommonKnowledge):
        def query_history(self, query, *, timeout_s):
            return ChatHistoryResult(
                source=dict(
                    kind="HISTORY_QUERY",
                    source_id="history:20",
                    title="DB 조회",
                    conditions=query.conditions,
                    code=None,
                    total=20,
                    synthetic_total=0,
                    snapshot="a" * 64,
                ),
                reports=[
                    dict(
                        source=dict(
                            kind="REPORT",
                            source_id=f"report:{n}",
                            title=f"보고서 {n}",
                            report_id=f"R{n}",
                            report_version=1,
                            synthetic=False,
                        ),
                        text="사람이 기록한 조치",
                    )
                    for n in range(min(20, query.conditions.limit))
                ],
                truncated=query.conditions.limit < 20,
            )

    client = FakeClient(
        reply(call("query_history", {"conditions": {"limit": 20}})),
        reply(
            submit(
                intent="MAINTENANCE_HISTORY",
                ids=("history:20",),
                text="승인 보고서 전체 20건입니다.",
            )
        ),
    )
    result = ask(client, Knowledge(), conditions=ChatSearchConditions(limit=20))
    assert result.status == "OK"
    assert result.applied_conditions.limit == 19
    assert result.sources[0].total == 20
