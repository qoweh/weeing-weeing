"""정형 건수 1회 종료·조건/최신성 검증·손실 없는 검토 근거 공유."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_chat_service import (
    CommonKnowledge,
    FakeClient,
    call,
    document,
    reply,
    search,
    submit,
)

from weeing_weeing.agent.chat import ToolChatService
from weeing_weeing.agent.chat_efficiency import grounding_payload
from weeing_weeing.agent.chat_grounding import verify_grounding
from weeing_weeing.agent.interface import load_faq_catalog
from weeing_weeing.agent.runtime import ToolInputError
from weeing_weeing.api.chat_knowledge import DatabaseChatKnowledge
from weeing_weeing.contracts import (
    ChatAnswerPart,
    ChatContext,
    ChatQuestion,
    MaintenanceReport,
)
from weeing_weeing.contracts.chat import ChatHistorySource
from weeing_weeing.contracts.chat_tools import ChatHistoryQuery


class Counts(CommonKnowledge):
    def __init__(self, total=6, *, stale=False, mismatch=False, broken=False):
        super().__init__()
        self.total, self.stale, self.mismatch, self.broken = (
            total,
            stale,
            mismatch,
            broken,
        )
        self.count_queries = []

    def count_history(self, query, *, timeout_s):
        self.count_queries.append(query)
        assert timeout_s > 0
        if self.broken:
            raise RuntimeError("database unavailable")
        conditions = query.conditions.model_copy(deep=True)
        if self.mismatch:
            conditions.asset_id = "DIFFERENT"
        return ChatHistorySource(
            source_id="count:1",
            title="승인 보고서 집계",
            conditions=conditions,
            code=query.code,
            total=self.total,
            synthetic_total=0,
            snapshot="a" * 64,
        )

    def is_searchable(self, source, *, timeout_s):
        self.reads.append(source)
        return not self.stale or len(self.reads) < 2


class NoReview(FakeClient):
    def generate_json(self, *args, **kwargs):
        raise AssertionError("Deterministic count must not call grounding")


def run(client, knowledge):
    service = ToolChatService(client, knowledge, load_faq_catalog())
    result = service.reply(
        ChatQuestion(
            request_id=uuid4(), question="2026년 11월 승인 정비 보고서는 몇 건이야?"
        ),
        context=ChatContext(),
        timeout_s=10,
    )
    return service, result


def count_call():
    return call(
        "query_history",
        {
            "purpose": "COUNT_ONLY",
            "conditions": {"date_from": "2026-11-01", "date_to": "2026-11-30"},
        },
    )


@pytest.mark.parametrize("total", [0, 6])
def test_count_finishes_in_one_call_without_free_answer_or_review(total):
    knowledge = Counts(total)
    client = NoReview(reply(count_call()))
    service, result = run(client, knowledge)
    assert result.status == "OK" and result.intent == "MAINTENANCE_HISTORY"
    assert f"총 {total}건" in result.parts[0].text
    assert "실제 정비 조치일" in result.parts[0].text
    assert "2026-11-01~2026-11-30" in result.parts[0].text
    assert len(client.calls) == len(service.last_run.calls) == 1
    assert len(knowledge.count_queries) == 1 and len(knowledge.reads) == 2
    assert not knowledge.searches
    assert result.sources[0].total == total
    assert result.parts[0].source_ids == ["count:1"]
    assert service.last_run.tool_names == ("query_history",)
    assert client.calls[0]["tools"][2][
        "input_schema"
    ]  # schema delivered without another classifier


@pytest.mark.parametrize("option", ["stale", "mismatch", "broken"])
def test_invalid_count_never_becomes_zero_or_success(option):
    _, response = run(NoReview(reply(count_call())), Counts(**{option: True}))
    assert response.status == "FAILED" and response.failure.code == "SEARCH_UNAVAILABLE"
    assert not response.parts and not response.sources


def test_count_cannot_drop_other_tools_in_a_compound_request():
    knowledge = Counts()
    client = FakeClient(reply(count_call(), search()), reply(submit()))
    _, result = run(client, knowledge)
    assert result.status == "OK" and result.intent == "MANUAL"
    assert not knowledge.count_queries and len(knowledge.searches) == 1
    assert len(client.calls) == 2


def test_count_and_list_share_identity_but_count_never_formats_report_body(monkeypatch):
    path = (
        Path(__file__).resolve().parents[2] / "data/history/synthetic_reports_v1.jsonl"
    )
    report = MaintenanceReport.model_validate_json(path.read_text().splitlines()[0])
    report.maintenance.actions_taken[0].at = datetime(2026, 10, 31, 15, tzinfo=UTC)
    outside = report.model_copy(deep=True)
    outside.report_id += "-outside"
    outside.maintenance.actions_taken[0].at = datetime(2026, 11, 30, 15, tzinfo=UTC)
    rows = [report, outside]
    knowledge = DatabaseChatKnowledge(
        None,
        SimpleNamespace(listed=lambda: []),
        SimpleNamespace(approved_reports=lambda: rows),
    )
    query = ChatHistoryQuery.model_validate(
        {"conditions": {"date_from": "2026-11-01", "date_to": "2026-11-30"}}
    )
    listed = knowledge.query_history(query, timeout_s=5)
    assert listed.source.total == 1
    monkeypatch.setattr(
        "weeing_weeing.api.chat_knowledge.report_search_hit",
        lambda *a: pytest.fail("count must not format report bodies"),
    )
    source = knowledge.count_history(query, timeout_s=5)
    assert source == listed.source
    assert knowledge.is_searchable(source, timeout_s=5)
    rows.clear()
    assert not knowledge.is_searchable(source, timeout_s=5)


def test_grounding_keeps_all_source_metadata_and_full_conditions_once():
    first = document().source
    second = first.model_copy(update={"source_id": "manual:2", "page": 7})
    sources = {"manual:1": first, "manual:2": second, "unused": first}
    full_text = "점검한다.\n\n단, 적용 조건을 만족할 때만 한다.\n\n예외와 금지 사항을 모두 보존한다."
    texts = {key: full_text for key in sources}
    parts = [
        ChatAnswerPart(
            kind="MANUAL", text="점검 안내", source_ids=["manual:1", "manual:2"]
        ),
        ChatAnswerPart(kind="MANUAL", text="적용 조건 확인", source_ids=["manual:1"]),
    ]
    payload = grounding_payload("점검 방법", parts, sources, texts)
    assert set(payload["evidence"]) == {"manual:1", "manual:2"}
    assert payload["evidence"]["manual:1"]["text"] == full_text
    assert payload["evidence"]["manual:2"]["text_ref"] == "manual:1"
    assert payload["evidence"]["manual:2"]["source"]["page"] == 7
    assert payload["parts"][0]["source_ids"] == ["manual:1", "manual:2"]
    assert payload["evidence_stats"]["sent_text_chars"] == len(full_text)
    assert payload["evidence_stats"]["referenced_text_chars"] == 3 * len(full_text)
    assert texts["manual:1"] == full_text

    class Reviewer:
        def generate_json(self, system, user, **kwargs):
            assert "text_ref" in system
            return '{"verdict":"SUPPORTED","unsupported_parts":[],"issues":[]}'

    assert verify_grounding(Reviewer(), payload, timeout_s=5).verdict == "SUPPORTED"
    with pytest.raises(ToolInputError):
        grounding_payload("점검", parts, sources, {})


def test_failed_tool_cannot_leave_a_stale_terminal_result():
    from weeing_weeing.agent.runtime import AgentTool, FinishTool, RunMemory, _run_tool

    memory = RunMemory()

    def broken(data, memory):
        memory.final_result = "must not escape"
        raise ToolInputError("retry required")

    tool = AgentTool("broken", "fake", {}, broken)
    finish = FinishTool("finish", "fake", {}, lambda data, memory: None)
    content, error = _run_tool(call("broken", {}), {"broken": tool}, finish, memory)
    assert error and "retry required" in content
    assert memory.final_result is None


def test_count_labels_synthetic_records_and_rejects_inconsistent_totals():
    from weeing_weeing.agent.chat_efficiency import history_count_response

    question = ChatQuestion(request_id=uuid4(), question="보고서 몇 건이야?")
    query = ChatHistoryQuery()
    source = ChatHistorySource(
        source_id="count:1",
        title="집계",
        conditions=query.conditions,
        total=6,
        synthetic_total=2,
        snapshot="a" * 64,
    )
    response = history_count_response(question, query, source)
    assert (
        "총 6건" in response.parts[0].text
        and "가상 자료 2건 포함" in response.parts[0].text
    )
    invalid = source.model_copy(update={"synthetic_total": 7})
    with pytest.raises(ValueError):
        history_count_response(question, query, invalid)
