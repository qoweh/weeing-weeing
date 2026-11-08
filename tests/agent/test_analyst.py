"""사건 분석 에이전트: 도구 호출 루프, 제출 검사, 실패 → FAILED. 가짜 LLM·검색기로."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from weeing_weeing.agent.analyst import IncidentAnalyzer, describe
from weeing_weeing.agent.interface import LlmTimeoutError, LlmUsage, get_analyzer
from weeing_weeing.agent.runtime import AgentError, AgentSpec, FinishTool, run_agent
from weeing_weeing.contracts import Evidence, Incident

ROOT = Path(__file__).resolve().parents[2]
INCIDENT = Incident.model_validate_json(
    (ROOT / "data/eval/incident_p03_demo.json").read_text("utf-8")
)
NOW = datetime(2026, 10, 29, tzinfo=UTC)
EV = Evidence(
    evidence_id="BTT-MANUAL:2.0:0007",
    doc_id="BTT-MANUAL",
    doc_version="2.0",
    citation="BTT-MANUAL 2.0 3절",
    text="감지면 오염, 광축·감도를 확인한다.",
)
OTHER = EV.model_copy(update={"evidence_id": "BTT-RULE:2.0:0004"})


def use(name, data, id="t1"):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=data)


def reply(*blocks):
    return SimpleNamespace(content=list(blocks), stop_reason="tool_use")


def search(query="P03 입구 장기 점유", id="t1", **extra):
    data = {"query": query, "code": None, "doc_type": None, "k": 5} | extra
    return use("search_evidence", data, id=id)


def submit(status="OK", cited=(EV.evidence_id,), id="t9"):
    causes = (
        [
            {
                "cause": "감지면 오염",
                "inspection_priority": "우선 확인",
                "priority_reason": "해당 코드의 매뉴얼에서 선행 점검으로 안내한다.",
                "basis": "입구 6.2초 true",
                "evidence_ids": list(cited),
            }
        ]
        if status == "OK"
        else []
    )
    return use(
        "submit_analysis",
        {
            "observed_facts": "입구 장기 점유",
            "suspected_causes": causes,
            "recommended_checks": ["센서 앞 물체 확인"],
            "recommended_actions": [],
            "actions_requiring_approval": ["재가동"],
            "additional_checks": [] if status == "OK" else ["현장 확인"],
            "limitations": None,
            "status": status,
        },
        id=id,
    )


class FakeLlm:
    provider = "fake"
    model_name = "llm"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.last_usage = None

    def create(self, *, system, messages, tools, timeout_s):
        # 호출 당시의 대화를 복사해 둔다(같은 리스트가 계속 늘어난다)
        self.calls.append({"messages": list(messages), "tools": tools})
        nxt = self.replies.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        self.last_usage = LlmUsage(100, 20, 1.0)
        return nxt


class FakeRetriever:
    def __init__(self, *results):
        self.results = list(results)
        self.queries = []

    def search(self, query, *, k=5, filters=None):
        self.queries.append((query, k, filters))
        nxt = self.results.pop(0) if self.results else []
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def analyzer(llm, retriever, **kw):
    return IncidentAnalyzer(llm, retriever, timeout_s=5, clock=lambda: NOW, **kw)


def last_tool_results(llm, call=-1):
    return llm.calls[call]["messages"][-1]["content"]


def test_search_then_submit_gives_cited_result():
    llm = FakeLlm(reply(search(code="BTT2-P03")), reply(submit()))
    retriever = FakeRetriever([EV, OTHER])
    a = analyzer(llm, retriever)

    result = a.analyze(INCIDENT)

    assert result.status == "OK"
    assert result.model == "fake/llm"
    assert result.prompt_version == "incident-analyst-v3"
    assert [e.evidence_id for e in result.evidence] == [EV.evidence_id]  # 인용한 것만
    assert retriever.queries == [("P03 입구 장기 점유", 5, {"code": "BTT2-P03"})]
    assert a.last_memory.turns == 2
    assert a.last_memory.usage.input_tokens == 200
    # 도구 정의: 검색 + 제출, strict
    names = [t["name"] for t in llm.calls[0]["tools"]]
    assert names == ["search_evidence", "submit_analysis"]
    assert all(t["strict"] for t in llm.calls[0]["tools"])
    # 검색 결과가 모델에게 돌아간다
    returned = json.loads(last_tool_results(llm)[0]["content"])
    assert returned[0]["evidence_id"] == EV.evidence_id
    assert returned[0]["relevance"] is None


def test_optional_check_citation_preserves_source_in_single_analysis():
    submission = submit()
    submission.input["check_citations"] = [
        {"check_index": 0, "evidence_ids": [OTHER.evidence_id]}
    ]
    result = analyzer(
        FakeLlm(reply(search()), reply(submission)), FakeRetriever([EV, OTHER])
    ).analyze(INCIDENT)
    assert result.status == "OK"
    assert {e.evidence_id for e in result.evidence} == {
        EV.evidence_id,
        OTHER.evidence_id,
    }


def test_citing_unsearched_id_is_sent_back_and_corrected():
    llm = FakeLlm(
        reply(search()),
        reply(submit(cited=("지어낸:근거:0001",))),
        reply(submit()),
    )
    result = analyzer(llm, FakeRetriever([EV])).analyze(INCIDENT)

    assert result.status == "OK"
    error = last_tool_results(llm)[0]
    assert error["is_error"] is True
    assert "검색 결과에 없는 근거 ID" in error["content"]


def test_no_evidence_gives_insufficient():
    llm = FakeLlm(reply(search()), reply(submit("INSUFFICIENT_EVIDENCE")))
    result = analyzer(llm, FakeRetriever([])).analyze(INCIDENT)
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.suspected_causes == [] and result.evidence == []
    assert last_tool_results(llm)[0]["content"] == "검색 결과 없음"


def test_relevance_is_preserved_in_tool_memory_and_final_result():
    evidence = EV.model_copy(update={"score": 0.033, "relevance": 0.82})
    llm = FakeLlm(reply(search()), reply(submit()))
    a = analyzer(llm, FakeRetriever([evidence]))
    result = a.analyze(INCIDENT)
    returned = json.loads(last_tool_results(llm)[0]["content"])
    assert returned[0]["relevance"] == 0.82
    assert a.last_memory.evidence[EV.evidence_id].relevance == 0.82
    assert result.evidence[0].score == 0.033
    assert result.evidence[0].relevance == 0.82


def test_filtered_rag_evidence_cannot_be_cited_by_agent():
    from weeing_weeing.rag.interface import HybridRetriever

    chunk = SimpleNamespace(
        chunk_id=EV.evidence_id,
        doc_id=EV.doc_id,
        doc_version=EV.doc_version,
        text=EV.text,
        metadata={"citation": EV.citation},
    )
    hit = SimpleNamespace(chunk=chunk, score=0.033, relevance=0.1)
    store = SimpleNamespace(hybrid_query=lambda *args, **kwargs: [hit])
    reranker = SimpleNamespace(rerank=lambda query, hits: hits)
    retriever = HybridRetriever(store, reranker=reranker, min_relevance=0.5)
    # 모델이 필터로 제외된 실제 ID를 써도 실행 기억에 없으므로 거부한다.
    llm = FakeLlm(
        reply(search()), reply(submit()), reply(submit("INSUFFICIENT_EVIDENCE"))
    )
    a = analyzer(llm, retriever)
    result = a.analyze(INCIDENT)
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.evidence == [] and a.last_memory.evidence == {}
    assert last_tool_results(llm)[0]["is_error"] is True


def test_invalid_reranker_output_is_failed_not_correctable_tool_input():
    llm = FakeLlm(reply(search()))
    result = analyzer(llm, FakeRetriever(ValueError("관련도 NaN"))).analyze(INCIDENT)
    assert result.status == "FAILED"
    assert "근거 검색 실패" in result.limitations
    assert len(llm.calls) == 1


@pytest.mark.parametrize("bad_filter", [{"code": "BTT2-Z99"}, {"doc_type": "other"}])
def test_invalid_search_filters_remain_correctable(bad_filter):
    llm = FakeLlm(reply(search(**bad_filter)), reply(search()), reply(submit()))
    retriever = FakeRetriever([EV])
    result = analyzer(llm, retriever).analyze(INCIDENT)
    assert result.status == "OK"
    assert len(retriever.queries) == 1
    assert last_tool_results(llm, call=1)[0]["is_error"] is True


def test_k_is_clamped_and_filters_passed():
    llm = FakeLlm(
        reply(search(k=50, doc_type="report")), reply(submit("INSUFFICIENT_EVIDENCE"))
    )
    retriever = FakeRetriever([])
    analyzer(llm, retriever).analyze(INCIDENT)
    assert retriever.queries[0][1:] == (8, {"doc_type": "report"})


def test_parallel_tool_results_return_in_one_message():
    llm = FakeLlm(
        reply(search(id="a"), search("벨트 정체", id="b")),
        reply(submit()),
    )
    analyzer(llm, FakeRetriever([EV], [])).analyze(INCIDENT)
    results = last_tool_results(llm)
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_text_only_reply_is_nudged_once_then_fails():
    talk = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="음")], stop_reason="end_turn"
    )
    llm = FakeLlm(talk, talk)
    result = analyzer(llm, FakeRetriever()).analyze(INCIDENT)
    assert result.status == "FAILED"
    assert "submit_analysis 없이" in result.limitations
    assert "submit_analysis 도구로" in llm.calls[1]["messages"][-1]["content"]


def test_turn_limit_fails():
    llm = FakeLlm(*[reply(search(id=str(i))) for i in range(3)])
    result = analyzer(llm, FakeRetriever(), max_turns=3).analyze(INCIDENT)
    assert result.status == "FAILED"
    assert "3번 안에" in result.limitations


@pytest.mark.parametrize(
    ("llm_reply", "retrieved"),
    [
        (LlmTimeoutError("120초 안에 응답 없음"), []),
        (
            reply(search()),
            [RuntimeError("qdrant down")],
        ),  # 검색 장애는 모델이 못 고친다
    ],
)
def test_infrastructure_failures_become_failed_result(llm_reply, retrieved):
    result = analyzer(FakeLlm(llm_reply), FakeRetriever(*retrieved)).analyze(INCIDENT)
    assert result.status == "FAILED"
    assert result.observed_facts.startswith("사건:")
    assert result.generated_at == NOW


def test_unknown_tool_and_bad_input_are_errors_for_the_model():
    llm = FakeLlm(
        reply(use("restart_conveyor", {}, id="x"), search(query="  ", id="y")),
        reply(submit("INSUFFICIENT_EVIDENCE")),
    )
    a = analyzer(llm, FakeRetriever())
    a.analyze(INCIDENT)
    errors = last_tool_results(llm)
    assert all(r["is_error"] for r in errors)
    assert "없는 도구" in errors[0]["content"]
    assert [c.ok for c in a.last_memory.tool_calls] == [False, False, True]


def test_describe_includes_codes_and_sensor_values():
    text = describe(INCIDENT)
    assert "BTT2-P03(입구 장기 점유)" in text
    assert "infeed_present=True" in text
    assert "run_cmd" in text


def test_runtime_works_with_any_finish_tool():
    # 멀티 에이전트로 넓힐 때 다른 역할도 같은 루프를 쓴다
    spec = AgentSpec(
        name="echo",
        system="s",
        tools=(),
        finish=FinishTool(
            "done",
            "끝",
            {"type": "object", "properties": {"x": {"type": "string"}}},
            lambda d, m: d["x"],
        ),
        prompt_version="v0",
        max_turns=2,
    )
    out, memory = run_agent(
        FakeLlm(reply(use("done", {"x": "ok"}))), spec, "task", timeout_s=1
    )
    assert out == "ok" and memory.turns == 1
    with pytest.raises(AgentError):
        run_agent(
            FakeLlm(reply(use("nope", {})), reply(use("nope", {}))),
            spec,
            "t",
            timeout_s=1,
        )


def test_get_analyzer_uses_settings(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_TURNS", "3")
    a = get_analyzer(FakeRetriever(), client=FakeLlm())
    assert a._spec.max_turns == 3


@pytest.mark.parametrize("change", ["legacy_only", "invalid_priority", "blank_reason"])
def test_model_must_submit_priority_and_reason_instead_of_likelihood(change):
    bad = submit()
    candidate = bad.input["suspected_causes"][0]
    if change == "legacy_only":
        candidate.pop("inspection_priority")
        candidate.pop("priority_reason")
        candidate["likelihood"] = "상"
    elif change == "invalid_priority":
        candidate["inspection_priority"] = "상"
    else:
        candidate["priority_reason"] = "  "
    llm = FakeLlm(reply(search()), reply(bad), reply(submit()))
    result = analyzer(llm, FakeRetriever([EV])).analyze(INCIDENT)
    assert result.status == "OK"
    cause = result.suspected_causes[0]
    assert cause.inspection_priority == "우선 확인" and cause.priority_reason.strip()
    assert cause.likelihood is None
    assert len(llm.calls) == 3  # 잘못된 제출을 수락하지 않고 같은 역할에서 수정한다.


def test_new_model_schema_has_no_probability_grade():
    from weeing_weeing.agent.analyst import analyst_spec

    spec = analyst_spec(FakeRetriever())
    candidate = spec.finish.input_schema["$defs"]["InspectionCauseDraft"]
    assert "likelihood" not in candidate["properties"]
    assert {"inspection_priority", "priority_reason"} <= set(candidate["required"])
    assert "현재 현장 점검 결과를 선행 조건으로 요구하지 않는다" in spec.system
    assert "안전상 선행 조건과 공식 SOP의 순서를 최우선" in spec.system
