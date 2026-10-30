"""#106: 관련도 필터와 #105 센서 검증을 같은 도구 실행에서 확인한다."""

from types import SimpleNamespace

import pytest
import test_sensor_window as sensor_tests
from test_analyst import EV, INCIDENT, FakeLlm, reply, search, submit, use
from test_sensor_window import QUERY, claim, lookup

from weeing_weeing.agent.analyst import IncidentAnalyzer
from weeing_weeing.rag.interface import HybridRetriever

records = sensor_tests.records


def retriever(relevance):
    chunk = SimpleNamespace(
        chunk_id=EV.evidence_id,
        doc_id=EV.doc_id,
        doc_version=EV.doc_version,
        text=EV.text,
        metadata={"citation": EV.citation},
    )
    hit = SimpleNamespace(chunk=chunk, score=0.033, relevance=relevance)
    store = SimpleNamespace(hybrid_query=lambda *a, **kw: [hit])
    reranker = SimpleNamespace(rerank=lambda query, hits: hits)
    return HybridRetriever(store, reranker=reranker, min_relevance=0.5)


def submission(status="OK", value=1200.0):
    block = submit(status)
    block.input["sensor_claims"] = [claim(value)]
    return block


def test_filtered_documents_do_not_become_sufficient_from_sensor_data(records):
    llm = FakeLlm(
        reply(search(), use("get_sensor_window", QUERY, id="s")),
        reply(submission()),
        reply(submission("INSUFFICIENT_EVIDENCE")),
    )
    analyzer = IncidentAnalyzer(
        llm, retriever(0.1), timeout_s=5, sensor_reader=lookup(records)
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert not result.evidence and not result.suspected_causes
    assert "rpm.mean=1200.0 rpm" in result.observed_facts
    assert [c.ok for c in analyzer.last_memory.tool_calls] == [True, True, False, True]


@pytest.mark.parametrize("gap", [False, True])
def test_high_relevance_never_bypasses_numeric_check_and_limits(records, gap):
    if gap:
        records = [records[0], records[-1]]
    llm = FakeLlm(
        reply(search(), use("get_sensor_window", QUERY, id="s")),
        reply(submission(value=9999.0)),
        reply(submission()),
    )
    analyzer = IncidentAnalyzer(
        llm, retriever(0.9), timeout_s=5, sensor_reader=lookup(records)
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK" and result.evidence[0].relevance == 0.9
    assert "rpm.mean=1200.0 rpm" in result.observed_facts
    assert "9999" not in result.observed_facts
    assert "센서 수치 불일치" in analyzer.last_memory.tool_calls[2].note
    if gap:
        assert "연속으로 간주하지" in result.limitations


def test_missing_sensor_data_does_not_invent_statistics(records):
    llm = FakeLlm(
        reply(search(), use("get_sensor_window", QUERY, id="s")), reply(submission())
    )
    analyzer = IncidentAnalyzer(
        llm, retriever(0.9), timeout_s=5, max_turns=2, sensor_reader=lookup([])
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "FAILED"
    assert "조회하지 않았거나 결측" in analyzer.last_memory.tool_calls[-1].note
