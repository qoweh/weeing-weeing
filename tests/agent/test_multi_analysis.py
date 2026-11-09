"""실제 LangGraph, 가짜 Claude·검색기로 분기·출처·상한·실패를 검증한다."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest

from weeing_weeing.agent.errors import LlmTimeoutError, LlmUsage
from weeing_weeing.agent.multi_analysis import MultiIncidentAnalyzer
from weeing_weeing.contracts import Evidence, Incident
from weeing_weeing.contracts.analysis_workflow import AnalysisCheckpoint

INCIDENT = Incident(
    incident_id="INC-multi",
    process_id="process",
    asset_id="motor",
    codes=["BTT2-M10"],
    severity="Error",
    first_detected_at=datetime(2026, 11, 4, tzinfo=UTC),
    last_detected_at=datetime(2026, 11, 4, tzinfo=UTC),
)
DOC = Evidence(
    evidence_id="doc:1",
    doc_id="manual",
    doc_version="1",
    citation="매뉴얼 1절",
    text="과열 시 안전 정지 후 부하와 냉각 상태를 점검한다.",
)
REPORT = Evidence(
    evidence_id="report:1",
    doc_id="report",
    doc_version="1",
    citation="승인 정비보고서",
    text="냉각팬 오염을 청소한 후 온도가 회복됐다. 현재 원인의 확정 근거는 아니다.",
)


def reply(name, **data):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name=name, input=data, id="tool")]
    )


def research(item, *, cases=()):
    return [
        reply("search_evidence", query="과열 점검", k=5),
        reply(
            "submit_research",
            findings=[{"statement": item.text, "evidence_ids": [item.evidence_id]}]
            if item
            else [],
            limitations=[],
            reference_cases=list(cases),
        ),
    ]


def draft(*ids, status="OK", reference_case_indices=()):
    return reply(
        "submit_analysis",
        observed_facts="",
        sensor_claims=[],
        suspected_causes=[
            {
                "cause": "냉각 불량 가능성",
                "inspection_priority": "우선 확인",
                "priority_reason": "해당 코드의 매뉴얼에서 선행 점검으로 안내한다.",
                "basis": "매뉴얼이 냉각 상태 점검을 안내한다. 현재 냉각 상태는 현장 확인이 필요하다.",
                "evidence_ids": list(ids),
                "unconfirmed": ["냉각 상태 현장 점검 결과"],
                "sensor_claim_indices": [],
            }
        ]
        if status == "OK"
        else [],
        recommended_checks=["안전 정지 후 냉각 상태 확인"] if status == "OK" else [],
        check_citations=[{"check_index": 0, "evidence_ids": list(ids)}]
        if status == "OK"
        else [],
        recommended_actions=[],
        action_citations=[],
        actions_requiring_approval=[],
        approval_citations=[],
        additional_checks=[],
        limitations=None,
        status=status,
        reference_case_indices=list(reference_case_indices),
    )


def verdict(value="PASS"):
    return reply(
        "submit_verification",
        verdict=value,
        summary="근거와 적용 조건 대조 결과",
        issues=[
            {
                "claim": "냉각 불량",
                "reason": "과거 사례만으로 확정할 수 없음",
                "evidence_ids": [REPORT.evidence_id],
                "correction": "가능성으로 표현",
            }
        ]
        if value in ("REVISE", "CAUTION")
        else [],
    )


class Client:
    provider, model_name = "fake", "claude"
    last_usage, last_attempts = None, 1

    def __init__(self, responses, calls):
        self.responses, self.calls = iter(responses), calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        self.last_usage = LlmUsage(40, 10, 0.0)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class Knowledge:
    def __init__(self, documents=(DOC,), reports=(REPORT,), current=True):
        self.documents, self.reports, self.current = (
            list(documents),
            list(reports),
            current,
        )
        self.queries = []

    def search(self, role, incident, query, *, k, timeout_s):
        assert incident == INCIDENT and timeout_s > 0
        self.queries.append((role, query))
        return self.documents if role == "documents" else self.reports

    def is_current(self, evidence, *, timeout_s):
        return self.current


def setup(*, verify=False, knowledge=None, plans=None, **options):
    plans = plans or {
        "documents": [research(DOC)],
        "reports": [research(REPORT)],
        "synthesis": [[draft(DOC.evidence_id, REPORT.evidence_id)]],
        "verification": [[verdict()]],
    }
    counts, calls = Counter(), []

    def factory(role):
        number = counts[role]
        counts[role] += 1
        return Client(plans[role][number], calls)

    analyzer = MultiIncidentAnalyzer(
        factory, knowledge or Knowledge(), verification_enabled=verify, **options
    )
    return analyzer, calls, counts


def finished(analyzer, role):
    return [
        run
        for run in analyzer.last_runs
        if run.role == role and run.status != "PENDING"
    ]


def reference_case(item):
    return dict(
        symptom="외함 온도 상승",
        action="냉각팬 청소",
        outcome="청소 후 온도 정상화",
        similarity="같은 설비·코드의 고온 증상",
        differences="현재 냉각팬 오염 여부는 미확인. 점검과 재가동 승인이 필요하다.",
        evidence_ids=[item.evidence_id],
    )


def test_selected_history_is_preserved_verbatim_and_its_sources_reach_verifier():
    other = REPORT.model_copy(update={"evidence_id": "report:2", "doc_id": "RPT-2"})
    cases = [reference_case(REPORT), reference_case(other)]
    analyzer, calls, _ = setup(
        verify=True,
        knowledge=Knowledge(reports=[REPORT, other]),
        plans={
            "documents": [research(DOC)],
            "reports": [research(REPORT, cases=cases)],
            "synthesis": [[draft(DOC.evidence_id, reference_case_indices=[1])]],
            "verification": [[verdict()]],
        },
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK"
    assert [case.model_dump() for case in result.reference_cases] == [cases[1]]
    assert {item.evidence_id for item in result.evidence} == {
        DOC.evidence_id,
        other.evidence_id,
    }
    assert len(finished(analyzer, "reports")[0].research.reference_cases) == 2
    assert '"reference_cases": [{' in calls[-1]["messages"][0]["content"]
    assert other.text in calls[-1]["messages"][0]["content"]


@pytest.mark.parametrize("indices", [[-1], [1], [True], ["0"], [0, 0]])
def test_unknown_duplicate_or_noninteger_case_selection_is_returned_for_correction(
    indices,
):
    analyzer, _, _ = setup(
        plans={
            "documents": [research(DOC)],
            "reports": [research(REPORT, cases=[reference_case(REPORT)])],
            "synthesis": [
                [
                    draft(DOC.evidence_id, reference_case_indices=indices),
                    draft(DOC.evidence_id, reference_case_indices=[0]),
                ]
            ],
        },
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK" and len(result.reference_cases) == 1
    assert finished(analyzer, "synthesis")[0].calls == 2


def test_revision_can_remove_a_case_without_overwriting_first_draft_or_research():
    analyzer, _, _ = setup(
        verify=True,
        plans={
            "documents": [research(DOC)],
            "reports": [research(REPORT, cases=[reference_case(REPORT)])],
            "synthesis": [
                [draft(DOC.evidence_id, reference_case_indices=[0])],
                [draft(DOC.evidence_id)],
            ],
            "verification": [[verdict("REVISE")], [verdict()]],
        },
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK" and result.reference_cases == []
    assert finished(analyzer, "synthesis")[0].analysis.reference_cases
    assert finished(analyzer, "reports")[0].research.reference_cases
    assert result.evidence == [DOC]


def test_three_agents_preserve_each_source_and_skip_verification():
    analyzer, calls, counts = setup()
    events = []
    result = analyzer.analyze_with_progress(INCIDENT, events.append)
    assert result.status == "OK"
    assert result.model == "fake/claude"
    assert len(calls) == 5
    assert counts["verification"] == 0
    assert finished(analyzer, "documents")[0].evidence == [DOC]
    assert finished(analyzer, "reports")[0].evidence == [REPORT]
    integrated = finished(analyzer, "synthesis")[0]
    assert {e.evidence_id for e in integrated.analysis.evidence} == {
        DOC.evidence_id,
        REPORT.evidence_id,
    }
    assert integrated.calls == 1 and integrated.input_tokens == 40
    assert finished(analyzer, "verification")[0].status == "SKIPPED"
    assert any(e.status == "RUNNING" for e in events)


def test_pre_inspection_priority_can_pass_without_current_inspection_or_reports():
    response = draft(DOC.evidence_id)
    response.content[0].input["suspected_causes"][0]["inspection_priority"] = (
        "후속 확인"
    )
    analyzer, calls, _ = setup(
        verify=True,
        plans={
            "documents": [research(DOC)],
            "reports": [research(None)],
            "synthesis": [[response]],
            "verification": [[verdict()]],
        },
        knowledge=Knowledge(reports=[]),
    )
    result = analyzer.analyze(INCIDENT)
    assert (
        result.status == "OK"
        and result.suspected_causes[0].inspection_priority == "후속 확인"
    )
    assert result.suspected_causes[0].priority_reason
    assert result.suspected_causes[0].likelihood is None
    assert finished(analyzer, "verification")[0].verification.verdict == "PASS"
    from weeing_weeing.agent.analyst import ASSESSMENT_RULES

    assert ASSESSMENT_RULES in calls[-2]["system"]
    assert ASSESSMENT_RULES in calls[-1]["system"]


def test_check_only_sources_are_preserved_and_missing_citations_are_rejected():
    from weeing_weeing.agent.analyst import submit_tool
    from weeing_weeing.agent.runtime import RunMemory

    memory = RunMemory()
    memory.remember([DOC])
    data = draft(DOC.evidence_id).content[0].input
    finish = submit_tool(INCIDENT, require_check_citations=True)
    assert finish.parse(data, memory).check_citations[0].check_index == 0
    data["check_citations"] = []
    with pytest.raises(ValueError, match="각 recommended_checks"):
        finish.parse(data, memory)
    extra = DOC.model_copy(update={"evidence_id": "doc:checks"})
    response = draft(DOC.evidence_id)
    response.content[0].input["check_citations"][0]["evidence_ids"] = [
        extra.evidence_id
    ]
    analyzer, _, _ = setup(
        knowledge=Knowledge(documents=[DOC, extra], reports=[]),
        plans={
            "documents": [research(DOC)],
            "reports": [research(None)],
            "synthesis": [[response]],
        },
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK"
    assert {e.evidence_id for e in result.evidence} == {
        DOC.evidence_id,
        extra.evidence_id,
    }


def test_four_agents_validate_actual_evidence():
    analyzer, calls, _ = setup(verify=True)
    assert analyzer.analyze(INCIDENT).status == "OK"
    assert len(calls) == 6
    check = finished(analyzer, "verification")[0]
    assert check.verification.verdict == "PASS"
    assert DOC.text in calls[-1]["messages"][0]["content"]
    assert REPORT.text in calls[-1]["messages"][0]["content"]


def test_report_timing_metadata_survives_research_tool_serialization():
    from weeing_weeing.contracts.analysis import ReportActionTiming

    timed = REPORT.model_copy(
        update={
            "report_timing": [
                ReportActionTiming(
                    action_index=0,
                    action_at=datetime(2026, 11, 3, 23, 58, tzinfo=UTC),
                    incident_at=INCIDENT.first_detected_at,
                    offset_seconds=-120,
                )
            ]
        }
    )
    analyzer, calls, _ = setup(verify=True, knowledge=Knowledge(reports=[timed]))
    result = analyzer.analyze(INCIDENT)
    report_run = finished(analyzer, "reports")[0]
    assert report_run.error_code is None
    assert result.status == "OK"
    assert report_run.evidence[0].report_timing[0].offset_seconds == -120
    assert '"offset_seconds": -120.0' in calls[-1]["messages"][0]["content"]


@pytest.mark.parametrize(
    "second,expected", [("PASS", "OK"), ("REVISE", "VERIFICATION_FAILED")]
)
def test_revision_is_limited_and_keeps_before_after(second, expected):
    plans = {
        "documents": [research(DOC)],
        "reports": [research(REPORT)],
        "synthesis": [
            [draft(DOC.evidence_id)],
            [draft(DOC.evidence_id, REPORT.evidence_id)],
        ],
        "verification": [[verdict("REVISE")], [verdict(second)]],
    }
    analyzer, calls, counts = setup(verify=True, plans=plans)
    result = analyzer.analyze(INCIDENT)
    assert result.status == expected
    assert len(calls) == 8 and counts["synthesis"] == counts["verification"] == 2
    assert [r.attempt for r in finished(analyzer, "synthesis")] == [1, 2]
    assert (
        finished(analyzer, "verification")[0].verification.issues[0].correction
        == "가능성으로 표현"
    )
    if expected != "OK":
        assert result.suspected_causes and result.recommended_checks
        assert result.check_citations[0].evidence_ids
        assert "가능성으로 표현" not in result.additional_checks


def test_no_history_is_not_a_search_failure():
    plans = {
        "documents": [research(DOC)],
        "reports": [research(None)],
        "synthesis": [[draft(DOC.evidence_id)]],
    }
    analyzer, _, _ = setup(knowledge=Knowledge(reports=[]), plans=plans)
    assert analyzer.analyze(INCIDENT).status == "OK"
    report_run = finished(analyzer, "reports")[0]
    assert report_run.status == "COMPLETED" and report_run.evidence == []


@pytest.mark.parametrize("statements", [["중복 발견"] * 6, ["긴 설명" * 140]])
def test_research_brief_can_be_corrected_without_discarding_original_sources(
    statements,
):
    extra = DOC.model_copy(
        update={"evidence_id": "doc:extra", "text": "검증에 필요한 상세 원문"}
    )
    valid = research(DOC)
    excessive = reply(
        "submit_research",
        findings=[
            {"statement": text, "evidence_ids": [DOC.evidence_id]}
            for text in statements
        ],
        limitations=[],
    )
    analyzer, calls, _ = setup(
        knowledge=Knowledge(documents=[DOC, extra], reports=[]),
        plans={
            "documents": [[valid[0], excessive, valid[1]]],
            "reports": [research(None)],
            "synthesis": [[draft(DOC.evidence_id)]],
        },
    )
    assert analyzer.analyze(INCIDENT).status == "OK"
    documents = finished(analyzer, "documents")[0]
    assert len(documents.research.findings) == 1
    assert {e.evidence_id for e in documents.evidence} == {
        DOC.evidence_id,
        extra.evidence_id,
    }
    assert extra.text in calls[-1]["messages"][0]["content"]


def sensor_record(sample_rows, seconds=0, temperature=95):
    from weeing_weeing.contracts import TelemetryRecord

    return TelemetryRecord.model_validate(sample_rows[0]).model_copy(
        update={
            "process_id": INCIDENT.process_id,
            "asset_id": INCIDENT.asset_id,
            "timestamp": INCIDENT.last_detected_at + timedelta(seconds=seconds),
            "motor_housing_temp_c": temperature,
        }
    )


def test_baseline_query_is_automatic_bounded_and_shared_without_model_tool_call(
    sample_rows,
):
    from weeing_weeing.agent.sensor_window import SensorBatch

    rows = [sensor_record(sample_rows, -1, 65), sensor_record(sample_rows)]
    reads = []

    def reader(incident, start, end, *, limit):
        reads.append((start, end, limit))
        return SensorBatch(rows, rows[-1].timestamp)

    analyzer, calls, counts = setup(verify=True, sensor_reader=reader)
    events = []
    result = analyzer.analyze_with_progress(INCIDENT, events.append)
    assert result.status == "OK" and len(reads) == 1
    assert reads[0][0] == INCIDENT.last_detected_at - timedelta(seconds=120)
    assert reads[0][1] == INCIDENT.last_detected_at + timedelta(microseconds=1)
    assert reads[0][2] == 513
    assert len(calls) == 6 and counts["synthesis"] == 1
    assert '"purpose": "baseline"' in calls[-2]["messages"][0]["content"]
    assert '"purpose": "baseline"' in calls[-1]["messages"][0]["content"]
    assert "기본 센서 이력: 저장 표본 2개" in result.observed_facts
    assert "최대 95" in result.observed_facts
    assert result.suspected_causes[0].basis.startswith("매뉴얼이")
    assert any(run.summary == "센서 이력 확인 중" for run in events)


def test_empty_baseline_is_a_limit_and_is_reused_for_revision():
    from weeing_weeing.agent.sensor_window import SensorBatch

    reads = []

    def reader(*args, **kwargs):
        reads.append(args)
        return SensorBatch([], None)

    revision = verdict("REVISE")
    revision.content[0].input["issues"][0]["evidence_ids"] = [DOC.evidence_id]
    analyzer, _, counts = setup(
        verify=True,
        sensor_reader=reader,
        plans={
            "documents": [research(DOC)],
            "reports": [research(None)],
            "synthesis": [[draft(DOC.evidence_id)], [draft(DOC.evidence_id)]],
            "verification": [[revision], [verdict()]],
        },
        knowledge=Knowledge(reports=[]),
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK" and len(reads) == 1 and counts["synthesis"] == 2
    assert "저장 표본 0개" in result.observed_facts
    assert "저장된 표본이 없다" in result.limitations


def test_baseline_read_failure_is_not_treated_as_no_data_and_can_resume():
    from weeing_weeing.agent.sensor_window import SensorBatch

    def broken(*args, **kwargs):
        raise RuntimeError("fake sensor read failed")

    analyzer, _, counts = setup(verify=True, sensor_reader=broken)
    checkpoints = []
    result = analyzer.resume_analysis(INCIDENT, lambda run, cp: checkpoints.append(cp))
    assert result.status == "FAILED" and counts["synthesis"] == 0
    assert finished(analyzer, "synthesis")[0].error_code == "RuntimeError"
    resumed, _, counts = setup(
        verify=True, sensor_reader=lambda *args, **kwargs: SensorBatch([], None)
    )
    assert (
        resumed.resume_analysis(
            INCIDENT, lambda *args: None, checkpoint=checkpoints[-1]
        ).status
        == "OK"
    )
    assert counts == {"synthesis": 1, "verification": 1}


def test_successful_baseline_is_not_queried_again_after_synthesis_timeout():
    from weeing_weeing.agent.sensor_window import SensorBatch

    reads = []

    def reader(*args, **kwargs):
        reads.append(args)
        return SensorBatch([], None)

    original, _, _ = setup(
        verify=True,
        sensor_reader=reader,
        plans={
            "documents": [research(DOC)],
            "reports": [research(REPORT)],
            "synthesis": [[LlmTimeoutError("fake timeout")]],
        },
    )
    checkpoints = []
    assert (
        original.resume_analysis(
            INCIDENT, lambda run, cp: checkpoints.append(cp)
        ).status
        == "FAILED"
    )
    saved = AnalysisCheckpoint.model_validate_json(checkpoints[-1].model_dump_json())
    assert saved.sensor_windows["window-1"]["purpose"] == "baseline"
    resumed, _, counts = setup(verify=True, sensor_reader=reader)
    assert (
        resumed.resume_analysis(INCIDENT, lambda *args: None, checkpoint=saved).status
        == "OK"
    )
    assert len(reads) == 1 and counts == {"synthesis": 1, "verification": 1}


def test_candidate_explanation_keeps_only_verified_referenced_observations(sample_rows):
    from weeing_weeing.agent.analyst import submit_tool
    from weeing_weeing.agent.baseline_sensors import ensure_baseline
    from weeing_weeing.agent.runtime import RunMemory
    from weeing_weeing.agent.sensor_window import SensorBatch

    memory = RunMemory()
    memory.remember([DOC])
    row = sensor_record(sample_rows)
    ensure_baseline(
        INCIDENT, lambda *args, **kwargs: SensorBatch([row], row.timestamp), memory
    )
    data = draft(DOC.evidence_id).content[0].input
    data["sensor_claims"] = [
        {
            "window_id": "window-1",
            "field": "motor_housing_temp_c",
            "statistic": "max",
            "value": 95,
        }
    ]
    data["suspected_causes"][0]["sensor_claim_indices"] = [0]
    data["suspected_causes"][0]["observations"] = ["검증되지 않은 999℃"]
    finish = submit_tool(INCIDENT, require_check_citations=True)
    parsed = finish.parse(data, memory)
    cause = parsed.suspected_causes[0]
    assert cause.basis == data["suspected_causes"][0]["basis"]
    assert cause.unconfirmed == ["냉각 상태 현장 점검 결과"]
    assert len(cause.observations) == 1 and "=95" in cause.observations[0]
    assert "999" not in cause.observations[0]
    assert "sensor_claim_indices" not in cause.model_dump()
    data["sensor_claims"][0]["value"] = 99
    with pytest.raises(ValueError, match="센서 수치 불일치"):
        finish.parse(data, memory)
    data["sensor_claims"][0]["value"] = 95
    data["suspected_causes"][0]["sensor_claim_indices"] = [1]
    with pytest.raises(ValueError, match="존재하지 않는"):
        finish.parse(data, memory)


def test_actions_require_real_citations_and_keep_action_only_sources():
    extra = DOC.model_copy(update={"evidence_id": "doc:action-only"})
    response = draft(DOC.evidence_id)
    data = response.content[0].input
    data["recommended_actions"] = ["담당자에게 점검 요청"]
    data["action_citations"] = [
        {"action_index": 0, "evidence_ids": [extra.evidence_id]}
    ]
    data["actions_requiring_approval"] = ["승인 후 재가동 판단"]
    data["approval_citations"] = [
        {"action_index": 0, "evidence_ids": [extra.evidence_id]}
    ]
    analyzer, _, _ = setup(
        knowledge=Knowledge(documents=[DOC, extra], reports=[]),
        plans={
            "documents": [research(DOC)],
            "reports": [research(None)],
            "synthesis": [[response]],
        },
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK" and {e.evidence_id for e in result.evidence} == {
        DOC.evidence_id,
        extra.evidence_id,
    }
    from weeing_weeing.agent.analyst import submit_tool
    from weeing_weeing.agent.runtime import RunMemory

    memory = RunMemory()
    memory.remember([DOC, extra])
    data["action_citations"] = []
    with pytest.raises(ValueError, match="모든 권고"):
        submit_tool(INCIDENT, require_check_citations=True).parse(data, memory)


@pytest.mark.parametrize("query", [None, 123, False, [], {}])
def test_invalid_research_query_can_be_corrected_instead_of_crashing(query):
    analyzer, _, _ = setup(
        knowledge=Knowledge(reports=[]),
        plans={
            "documents": [research(DOC)],
            "reports": [[reply("search_evidence", query=query, k=5), *research(None)]],
            "synthesis": [[draft(DOC.evidence_id)]],
        },
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK"
    assert finished(analyzer, "reports")[0].status == "COMPLETED"


def test_nullable_optional_search_limit_uses_default():
    plan = research(None)
    plan[0].content[0].input["k"] = None
    analyzer, calls, _ = setup(
        knowledge=Knowledge(reports=[]),
        plans={
            "documents": [research(DOC)],
            "reports": [plan],
            "synthesis": [[draft(DOC.evidence_id)]],
        },
    )
    assert analyzer.analyze(INCIDENT).status == "OK"
    tools = [
        tool
        for call in calls
        for tool in call["tools"]
        if tool["name"] == "search_evidence"
    ]
    assert tools and all(
        tool["input_schema"]["properties"]["query"]["type"] == "string"
        for tool in tools
    )


def test_empty_both_returns_insufficient_evidence():
    plans = {
        "documents": [research(None)],
        "reports": [research(None)],
        "synthesis": [[draft(status="INSUFFICIENT_EVIDENCE")]],
    }
    analyzer, _, _ = setup(knowledge=Knowledge(documents=[], reports=[]), plans=plans)
    assert analyzer.analyze(INCIDENT).status == "INSUFFICIENT_EVIDENCE"


def test_invalid_research_citation_blocks_synthesis():
    plans = {
        "documents": [
            [
                reply("search_evidence", query="과열", k=5),
                reply(
                    "submit_research",
                    findings=[{"statement": "위조", "evidence_ids": ["missing"]}],
                    limitations=[],
                ),
            ]
        ],
        "reports": [research(REPORT)],
    }
    analyzer, _, counts = setup(plans=plans, max_turns=2)
    assert analyzer.analyze(INCIDENT).status == "FAILED"
    assert counts["synthesis"] == 0
    assert finished(analyzer, "documents")[0].status == "FAILED"


def test_changed_source_does_not_return_stale_ok():
    analyzer, _, _ = setup(knowledge=Knowledge(current=False))
    assert analyzer.analyze(INCIDENT).status == "FAILED"


def test_call_budget_is_shared_by_all_roles():
    analyzer, calls, _ = setup(verify=True, max_calls=3)
    assert analyzer.analyze(INCIDENT).status == "FAILED"
    assert len(calls) <= 3


def test_total_deadline_blocks_queries_and_later_roles(monkeypatch):
    from weeing_weeing.agent import multi_analysis

    now = [0.0]
    monkeypatch.setattr(multi_analysis.time, "monotonic", lambda: now[0])
    calls = []

    class Slow(Client):
        def create(self, **kwargs):
            now[0] += 61
            return super().create(**kwargs)

    def factory(role):
        return Slow([reply("search_evidence", query="점검", k=5)], calls)

    knowledge = Knowledge()
    analyzer = MultiIncidentAnalyzer(factory, knowledge, timeout_s=60)
    assert analyzer.analyze(INCIDENT).status == "FAILED"
    # 두 조사 요청이 마감 전에 함께 시작될 수 있지만 이후 검색은 실행하지 않는다.
    assert 1 <= len(calls) <= 2 and not knowledge.queries


def test_verification_service_failure_is_not_pass_or_silently_skipped():
    plans = {
        "documents": [research(DOC)],
        "reports": [research(REPORT)],
        "synthesis": [[draft(DOC.evidence_id)]],
        "verification": [[RuntimeError("fake API unavailable")]],
    }
    analyzer, _, _ = setup(verify=True, plans=plans)
    assert analyzer.analyze(INCIDENT).status == "FAILED"
    assert finished(analyzer, "verification")[0].status == "FAILED"


def test_progress_storage_error_propagates_without_paid_replay():
    analyzer, calls, _ = setup()

    def unavailable(stage):
        raise RuntimeError("fake stage storage unavailable")

    with pytest.raises(RuntimeError, match="storage unavailable"):
        analyzer.analyze_with_progress(INCIDENT, unavailable)
    assert not calls


def test_research_roles_can_run_independently_in_parallel():
    barrier = Barrier(2, timeout=5)

    class ParallelKnowledge(Knowledge):
        def search(self, *args, **kwargs):
            barrier.wait()
            return super().search(*args, **kwargs)

    analyzer, _, _ = setup(knowledge=ParallelKnowledge())
    assert analyzer.analyze(INCIDENT).status == "OK"


@pytest.mark.parametrize(
    "role,attempt",
    [
        ("documents", 1),
        ("reports", 1),
        ("synthesis", 1),
        ("verification", 1),
        ("synthesis", 2),
        ("verification", 2),
    ],
)
def test_resume_only_failed_stage_and_its_successors(role, attempt):
    revised = attempt == 2
    plans = {
        "documents": [research(DOC)],
        "reports": [research(REPORT)],
        "synthesis": [
            [draft(DOC.evidence_id)],
            [draft(DOC.evidence_id, REPORT.evidence_id)],
        ],
        "verification": [[verdict("REVISE" if revised else "PASS")], [verdict()]],
    }
    plans[role][attempt - 1] = [LlmTimeoutError("fake timeout")]
    original, _, _ = setup(verify=True, plans=plans)
    checkpoints = []
    assert (
        original.resume_analysis(
            INCIDENT, lambda run, checkpoint: checkpoints.append(checkpoint)
        ).status
        == "FAILED"
    )
    # 프로세스가 바뀐 것처럼 JSON으로 왕복한다. 내부 대화 기록은 필요 없다.
    saved = AnalysisCheckpoint.model_validate_json(checkpoints[-1].model_dump_json())
    resumed, calls, counts = setup(verify=False)
    result = resumed.resume_analysis(INCIDENT, lambda *args: None, checkpoint=saved)
    assert result.status == "OK"
    expected = {
        "documents": int(role == "documents"),
        "reports": int(role == "reports"),
        "synthesis": int(role in ("documents", "reports", "synthesis")),
        "verification": 1,
    }
    assert dict(counts) == {key: value for key, value in expected.items() if value}
    if role == "verification":
        assert len(calls) == 1
    if revised:
        assert [r.attempt for r in finished(resumed, "synthesis")] == [1, 2]
        assert saved.verification_enabled is True
        if role == "verification":
            assert result.model_dump(exclude={"generated_at"}) == finished(
                original, "synthesis"
            )[-1].analysis.model_dump(exclude={"generated_at"})
            assert REPORT.text in calls[-1]["messages"][0]["content"]


def test_resume_retains_sensor_statistics_without_refetch_and_uses_fresh_budget():
    from weeing_weeing.agent.sensor_window import SensorBatch

    readings = []

    def reader(*args, **kwargs):
        readings.append(args)
        return SensorBatch([], None)

    plans = {
        "documents": [research(DOC)],
        "reports": [research(REPORT)],
        "synthesis": [
            [
                reply(
                    "get_sensor_window",
                    before_seconds=10,
                    after_seconds=0,
                    fields=["motor_housing_temp_c"],
                ),
                draft(DOC.evidence_id),
            ]
        ],
        "verification": [[LlmTimeoutError("fake timeout")]],
    }
    original, _, _ = setup(verify=True, plans=plans, sensor_reader=reader)
    snapshots = []
    assert (
        original.resume_analysis(INCIDENT, lambda run, cp: snapshots.append(cp)).status
        == "FAILED"
    )
    saved = AnalysisCheckpoint.model_validate_json(snapshots[-1].model_dump_json())
    assert (
        saved.sensor_windows["window-1"]["fields"]["motor_housing_temp_c"][
            "statistics"
        ]["valid_count"]
        == 0
    )
    resumed, calls, counts = setup(
        verify=True,
        max_calls=1,
        knowledge=Knowledge(current=False),
        sensor_reader=reader,
    )
    assert (
        resumed.resume_analysis(INCIDENT, lambda *args: None, checkpoint=saved).status
        == "OK"
    )
    assert len(readings) == 2 and counts == {"verification": 1}
    assert saved.sensor_windows["window-1"]["purpose"] == "baseline"
    assert '"window-1"' in calls[0]["messages"][0]["content"]


def test_repeated_manual_resume_keeps_revision_attempt_and_does_not_repeat_success():
    original, _, _ = setup(
        verify=True,
        plans={
            "documents": [research(DOC)],
            "reports": [research(REPORT)],
            "synthesis": [[draft(DOC.evidence_id)], [draft(DOC.evidence_id)]],
            "verification": [[verdict("REVISE")], [LlmTimeoutError("fake timeout")]],
        },
    )
    snapshots = []

    def callback(run, cp):
        snapshots.append(cp)

    assert original.resume_analysis(INCIDENT, callback).status == "FAILED"
    failed, _, counts = setup(
        verify=True, plans={"verification": [[LlmTimeoutError("fake timeout")]]}
    )
    assert (
        failed.resume_analysis(INCIDENT, callback, checkpoint=snapshots[-1]).status
        == "FAILED"
    )
    assert counts == {"verification": 1}
    resumed, _, counts = setup(
        verify=True, plans={"verification": [[verdict("REVISE")]]}
    )
    assert (
        resumed.resume_analysis(INCIDENT, callback, checkpoint=snapshots[-1]).status
        == "VERIFICATION_FAILED"
    )
    assert counts == {"verification": 1}
    assert finished(resumed, "verification")[-1].attempt == 2


def traced_setup(fake, **options):
    """역할 클라이언트와 분석기가 같은 가짜 Langfuse 기록기를 쓴다(#207)."""
    from test_tracing import tracer

    shared = tracer(fake)
    analyzer, calls, counts = setup(**options)
    factory = analyzer.client_factory

    def traced_factory(role):
        client = factory(role)
        client.tracer = shared
        return client

    analyzer.client_factory = traced_factory
    analyzer.tracer = shared
    return analyzer, calls


def scores(fake):
    return {s["name"]: s["value"] for s in fake.scores}


def test_analysis_is_one_trace_with_roles_nested_and_status_score():
    from test_tracing import FakeLangfuse

    fake = FakeLangfuse()
    analyzer, calls = traced_setup(fake, verify=True)
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK"
    # 병렬 조사 노드도 같은 trace 안에 들어가야 trace 속성이 한 번만 붙는다.
    assert [p["trace_name"] for p in fake.propagated] == ["incident-analysis"]
    root = fake.propagated[0]
    assert root["session_id"] == INCIDENT.incident_id
    assert "multi-analysis-v7" in root["tags"]
    assert fake.observations[0].kwargs["name"] == "incident-analysis"
    agents = {
        o.kwargs["name"] for o in fake.observations if o.kwargs["as_type"] == "agent"
    }
    assert agents == {
        "incident-documents",
        "incident-reports",
        "incident-synthesis",
        "incident-verification",
    }
    assert scores(fake) == {
        "analysis.status": "OK",
        "analysis.llm_calls": len(calls),
    }
    meta = fake.observations[0].updates["metadata"]
    assert meta["status"] == "OK" and meta["resumed"] is False


def test_failed_analysis_records_failure_code():
    from test_tracing import FakeLangfuse

    fake = FakeLangfuse()
    analyzer, _ = traced_setup(
        fake,
        plans={
            "documents": [[LlmTimeoutError("느림")]],
            "reports": [research(REPORT)],
            "synthesis": [[draft(REPORT.evidence_id)]],
            "verification": [[verdict()]],
        },
    )
    result = analyzer.analyze(INCIDENT)
    recorded = scores(fake)
    assert recorded["analysis.status"] == result.status
    if result.status == "FAILED":
        assert recorded["analysis.failure_code"] == result.limitations


def test_analysis_without_tracer_still_runs():
    analyzer, _, _ = setup()
    assert analyzer.analyze(INCIDENT).status == "OK"


def test_get_analyzer_gives_multi_analyzer_a_tracer():
    import dataclasses

    from weeing_weeing.agent.interface import get_analyzer
    from weeing_weeing.agent.tracing import NULL_TRACER
    from weeing_weeing.config import get_settings

    settings = dataclasses.replace(get_settings(), langfuse_base_url="")
    analyzer = get_analyzer(
        None, settings=settings, knowledge=Knowledge(), mode="multi"
    )
    assert isinstance(analyzer, MultiIncidentAnalyzer)
    assert analyzer.tracer is NULL_TRACER


def test_caution_returns_analysis_without_second_synthesis():
    plans = {
        "documents": [research(DOC)],
        "reports": [research(REPORT)],
        "synthesis": [[draft(DOC.evidence_id, REPORT.evidence_id)]],
        "verification": [[verdict("CAUTION")]],
    }
    analyzer, _, counts = setup(verify=True, plans=plans)
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK"
    assert counts["synthesis"] == 1
    assert counts["verification"] == 1
    assert "검증 주의사항" in result.limitations
    assert "가능성으로 표현" in result.limitations
    assert finished(analyzer, "verification")[0].verification.verdict == "CAUTION"
