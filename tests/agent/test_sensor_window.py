"""#105: 표본 요약·결측·범위 제한과 가짜 LLM 제출 수치 검증."""

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_analyst import (
    EV,
    INCIDENT,
    FakeLlm,
    FakeRetriever,
    reply,
    search,
    submit,
    use,
)

from weeing_weeing.agent.analyst import IncidentAnalyzer, submit_tool
from weeing_weeing.agent.runtime import RunMemory
from weeing_weeing.agent.sensor_window import (
    MAX_ROWS,
    SensorBatch,
    SensorClaim,
    verified_facts,
    window_tool,
)
from weeing_weeing.contracts import TelemetryRecord


@pytest.fixture
def records(sample_rows):
    base = TelemetryRecord.model_validate(sample_rows[0])
    return [
        base.model_copy(
            update={
                "timestamp": INCIDENT.last_detected_at + timedelta(seconds=offset),
                "asset_id": INCIDENT.asset_id,
                "process_id": INCIDENT.process_id,
                "rpm": rpm,
                "infeed_present": present,
                "motor_housing_temp_c": temp,
            }
        )
        for offset, rpm, present, temp in [
            (-1, 1000.0, False, None),
            (-0.5, 1200.0, True, 60.0),
            (0, 1400.0, True, 62.0),
        ]
    ]


def lookup(records):
    return lambda *args, **kwargs: SensorBatch(
        records, records[-1].timestamp if records else None
    )


QUERY = {
    "before_seconds": 1,
    "after_seconds": 0,
    "fields": ["rpm", "infeed_present", "motor_housing_temp_c"],
}


def collect(records, query=None):
    memory = RunMemory()
    out = window_tool(INCIDENT, lookup(records)).handler(query or QUERY, memory)
    return json.loads(out), memory


def claim(value=1200.0, **updates):
    return {
        "window_id": "window-1",
        "field": "rpm",
        "statistic": "mean",
        "value": value,
    } | updates


def test_summary_has_no_raw_rows_and_preserves_units_missing_and_transitions(records):
    data, _ = collect(records)
    assert data["sample_count"] == 3
    assert "records" not in data
    assert data["anchor"] == INCIDENT.last_detected_at.isoformat()
    rpm = data["fields"]["rpm"]
    assert rpm["unit"] == "rpm"
    assert rpm["statistics"] == {
        "min": 1000.0,
        "max": 1400.0,
        "mean": 1200.0,
        "first": 1000.0,
        "last": 1400.0,
        "delta": 400.0,
        "valid_count": 3,
        "missing_count": 0,
    }
    assert data["fields"]["motor_housing_temp_c"]["statistics"]["missing_count"] == 1
    assert data["fields"]["infeed_present"]["statistics"]["true_count"] == 2
    assert len(data["fields"]["infeed_present"]["changes"]) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"before_seconds": -1},
        {"before_seconds": 121},
        {"before_seconds": True},
        {"after_seconds": 31},
        {"fields": []},
        {"fields": ["asset_id"]},
        {"incident_id": "another"},
        {"before_seconds": "1"},
    ],
)
def test_rejects_unbounded_or_out_of_scope_query(records, changes):
    with pytest.raises(ValidationError):
        collect(records, QUERY | changes)


def test_empty_and_future_are_explicit_not_normal():
    data, _ = collect([], QUERY | {"after_seconds": 10})
    assert data["sample_count"] == 0
    assert data["fields"]["rpm"]["statistics"] == {"valid_count": 0, "missing_count": 0}
    assert any("미래" in n for n in data["notes"])
    assert any("정상으로 판단할 수 없다" in n for n in data["notes"])


def test_gap_and_partial_bounds_are_explicit(records):
    data, _ = collect(
        [records[0], records[-1]], QUERY | {"before_seconds": 2, "after_seconds": 2}
    )
    assert data["max_gap_seconds"] == 1
    assert any("연속으로 간주하지" in n for n in data["notes"])
    assert any("시작 시각" in n for n in data["notes"])
    assert any("종료 시각" in n for n in data["notes"])


def test_short_window_reports_boundaries_without_inventing_120_seconds(records):
    data, _ = collect(records, QUERY | {"before_seconds": 120})
    quality = data["quality"]
    assert quality["requested_duration_s"] == 120
    assert quality["observed_span_s"] == 1
    assert quality["leading_unobserved_s"] == 119
    assert quality["max_gap_scope"] == "returned_samples_only"
    assert quality["origins"] == {"UNKNOWN": 3}
    assert quality["unobserved_intervals"][0]["duration_s"] == 119


@pytest.mark.parametrize(
    "period,gap,missing", [(1, 1.002, False), (0.5, 1.002, True), (1, 2.5, True)]
)
def test_gap_detection_uses_declared_period_instead_of_fixed_half_second(
    records, period, gap, missing
):
    from weeing_weeing.contracts.telemetry import TelemetryProvenance

    rows = [
        records[0].model_copy(
            update={"timestamp": INCIDENT.last_detected_at - timedelta(seconds=gap)}
        ),
        records[-1],
    ]
    source = TelemetryProvenance(origin="SIMULATION", expected_interval_s=period)
    batch = SensorBatch(
        rows, rows[-1].timestamp, {row.timestamp: source for row in rows}
    )
    memory = RunMemory()
    data = json.loads(
        window_tool(INCIDENT, lambda *a, **k: batch).handler(
            QUERY | {"before_seconds": 5}, memory
        )
    )
    quality = data["quality"]
    assert quality["expected_interval_s"] == period
    assert quality["origins"] == {"SIMULATION": 2}
    assert (
        any(
            item["kind"] == "between_samples"
            for item in quality["unobserved_intervals"]
        )
        == missing
    )
    assert "시뮬레이션 값" in " ".join(data["notes"])


def test_mixed_or_unknown_origins_and_periods_are_not_guessed(records):
    from weeing_weeing.contracts.telemetry import TelemetryProvenance

    source = TelemetryProvenance(origin="MEASURED", expected_interval_s=1)
    batch = SensorBatch(records, records[-1].timestamp, {records[0].timestamp: source})
    memory = RunMemory()
    data = json.loads(
        window_tool(INCIDENT, lambda *a, **k: batch).handler(QUERY, memory)
    )
    assert data["quality"]["expected_interval_s"] is None
    assert data["quality"]["origins"] == {"MEASURED": 1, "UNKNOWN": 2}
    assert any("실측 검증이 아니다" in note for note in data["notes"])


@pytest.mark.parametrize(
    "changes",
    [
        {"asset_id": "other"},
        {"process_id": "other"},
        {"timestamp": INCIDENT.last_detected_at + timedelta(seconds=1)},
    ],
)
def test_reader_cannot_leak_other_asset_or_time(records, changes):
    with pytest.raises(RuntimeError, match="범위 불일치"):
        collect([records[0].model_copy(update=changes)])


def test_output_bounded_and_nonfinite_values_missing(records):
    many = [
        records[0].model_copy(
            update={
                "timestamp": INCIDENT.last_detected_at - timedelta(milliseconds=i),
                "rpm": float(i),
            }
        )
        for i in range(MAX_ROWS + 1)
    ]
    data, _ = collect(many)
    assert data["truncated"] and data["sample_count"] == MAX_ROWS
    assert len(data["fields"]["rpm"]["changes"]) == 16
    assert data["fields"]["rpm"]["changes_truncated"]
    data, _ = collect([records[0].model_copy(update={"rpm": float("nan")})])
    assert "mean" not in data["fields"]["rpm"]["statistics"]


@pytest.mark.parametrize(
    "changes",
    [
        {"value": 999.0},
        {"window_id": "unknown"},
        {"field": "dc_bus_voltage_v"},
        {"statistic": "true_count"},
        {"value": True},
    ],
)
def test_claim_mismatch_or_unqueried_value_rejected(records, changes):
    _, memory = collect(records)
    with pytest.raises(ValueError):
        verified_facts([SensorClaim.model_validate(claim() | changes)], memory)


def test_bool_and_missing_claims(records):
    _, memory = collect(records)
    verified_facts(
        [
            SensorClaim.model_validate(
                claim(False, field="infeed_present", statistic="first")
            )
        ],
        memory,
    )
    with pytest.raises(ValueError):
        verified_facts(
            [
                SensorClaim.model_validate(
                    claim(0, field="infeed_present", statistic="first")
                )
            ],
            memory,
        )
    empty, memory = collect([])
    with pytest.raises(ValueError):
        verified_facts([SensorClaim.model_validate(claim())], memory)
    assert empty["sample_count"] == 0


def test_wrong_number_returns_error_then_corrected_in_real_tool_loop(records):
    bad = submit()
    bad.input["sensor_claims"] = [claim(999.0)]
    good = submit()
    good.input["sensor_claims"] = [claim()]
    good.input["observed_facts"] = "rpm 999999.0, 물체가 없음"
    good.input["suspected_causes"][0]["basis"] = "999999.0rpm"
    llm = FakeLlm(
        reply(search(), use("get_sensor_window", QUERY, id="s1")),
        reply(bad),
        reply(good),
    )
    analyzer = IncidentAnalyzer(
        llm, FakeRetriever([EV]), timeout_s=5, sensor_reader=lookup(records)
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "OK"
    assert result.prompt_version == "incident-analyst-v3"
    assert "rpm.mean=1200.0 rpm" in result.observed_facts
    assert "999999" not in result.observed_facts + result.suspected_causes[0].basis
    assert "물체가 없음" not in result.observed_facts
    assert [c.ok for c in analyzer.last_memory.tool_calls] == [True, True, False, True]
    assert "센서 수치 불일치" in analyzer.last_memory.tool_calls[2].note
    assert result.limitations


def test_memory_does_not_cross_runs(records):
    _, memory = collect(records)
    data = submit("INSUFFICIENT_EVIDENCE").input | {"sensor_claims": [claim()]}
    submit_tool(INCIDENT).parse(data, memory)
    with pytest.raises(ValueError, match="조회하지 않았"):
        submit_tool(INCIDENT).parse(data, RunMemory())


def test_reader_failure_is_failed_result():
    def failed(*a, **kw):
        raise RuntimeError("offline")

    llm = FakeLlm(reply(use("get_sensor_window", QUERY)))
    analyzer = IncidentAnalyzer(llm, FakeRetriever(), timeout_s=5, sensor_reader=failed)
    assert analyzer.analyze(INCIDENT).status == "FAILED"


def test_sensor_tools_keep_incident_session_and_v2_tag_in_tracing(records):
    from test_tracing import FakeLangfuse, tracer

    fake = FakeLangfuse()
    submission = submit("INSUFFICIENT_EVIDENCE")
    submission.input["sensor_claims"] = [claim()]
    llm = FakeLlm(reply(use("get_sensor_window", QUERY)), reply(submission))
    llm.tracer = tracer(fake)
    analyzer = IncidentAnalyzer(
        llm, FakeRetriever(), timeout_s=5, sensor_reader=lookup(records)
    )
    result = analyzer.analyze(INCIDENT)
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert "rpm.mean=1200.0 rpm" in result.observed_facts
    assert fake.propagated[0]["session_id"] == INCIDENT.incident_id
    assert fake.propagated[0]["tags"] == ["analyze", "incident-analyst-v3"]
    assert [o.kwargs["name"] for o in fake.observations] == [
        "incident-analyst",
        "get_sensor_window",
        "submit_analysis",
    ]
