"""31개 코드 공통 수명주기와 수치·광전·시간창 룰의 의미를 검증한다."""

from datetime import datetime, timedelta, timezone

import pytest

from weeing_weeing.contracts import (
    IncidentStatus,
    SensorEvidence,
    Severity,
    TelemetryRecord,
)
from weeing_weeing.contracts.codes import CODES
from weeing_weeing.detector.builtin_rules import NUMERIC_RULES
from weeing_weeing.detector.interface import RuleAssessment, RuleDetector, RulePolicy

T0 = datetime(2026, 10, 5, tzinfo=timezone.utc)
CONTEXT = {
    "run_cmd": True,
    "run_started_at": T0 - timedelta(seconds=600),
    "fixed_speed": True,
    "same_load": True,
    "vibration_comparable": True,
    "recipe_id": "demo-1",
    "events_reliable": True,
    "downstream_ready": True,
    "continuous_infeed": True,
}


def row(second, **values):
    data = {name: (lower + upper) / 2 for name, lower, upper, *_ in NUMERIC_RULES}
    data.update(infeed_present=False, outfeed_present=False)
    data.update(values)
    return TelemetryRecord(
        record_id=f"row-{second}",
        timestamp=T0 + timedelta(seconds=second),
        process_id="process",
        asset_id="asset",
        schema_version="3.0.0",
        **data,
    )


def assessment(code, severity, **values):
    return RuleAssessment(
        code, severity, evidence=[SensorEvidence(field="rpm", value=990)], **values
    )


@pytest.mark.parametrize("code", CODES)
def test_every_code_uses_same_confirm_escalate_recover_and_recur_path(code):
    detector = RuleDetector(enabled_codes={code}, policies={code: RulePolicy(1, 1, 2)})
    assert (
        detector.process_assessments(row(0), [assessment(code, Severity.WARNING)]) == []
    )
    warning = detector.process_assessments(
        row(1), [assessment(code, Severity.WARNING)]
    )[0]
    detector.process_assessments(row(2), [assessment(code, Severity.ERROR)])
    error = detector.process_assessments(row(3), [assessment(code, Severity.ERROR)])[0]
    assert error.incident_id == warning.incident_id
    assert error.severity == Severity.ERROR
    assert error.first_detected_at == T0
    assert error.confirmed_at == row(1).timestamp
    assert detector.process_assessments(row(4), []) == []  # 미제공은 정상이 아님
    assert (
        detector.process_assessments(row(5), [assessment(code, Severity.NORMAL)]) == []
    )
    assert (
        detector.process_assessments(row(6), [assessment(code, Severity.NORMAL)]) == []
    )
    recovered = detector.process_assessments(
        row(7), [assessment(code, Severity.NORMAL)]
    )[0]
    assert recovered.status == IncidentStatus.RECOVERED
    assert recovered.last_detected_at == row(3).timestamp
    assert recovered.evidence == error.evidence
    detector.process_assessments(row(8), [assessment(code, Severity.WARNING)])
    recurring = detector.process_assessments(
        row(9), [assessment(code, Severity.WARNING)]
    )[0]
    assert recurring.incident_id != error.incident_id


@pytest.mark.parametrize("spec", NUMERIC_RULES, ids=lambda s: s[0])
@pytest.mark.parametrize("direction", ["L", "H"])
def test_all_numeric_error_boundaries_duration_and_normal_recovery(spec, direction):
    name, lower, upper, b, c, low, high, unit, duration = spec
    code = f"BTT2-{low if direction == 'L' else high}"
    detector = RuleDetector(enabled_codes={code})
    for second in range(duration + 1):
        changed = detector.process(
            row(second, **{name: b if direction == "L" else c}), CONTEXT
        )
        if second < duration:
            assert changed == []
    assert changed[0].severity == Severity.ERROR
    assert changed[0].direction == direction
    assert changed[0].evidence[0].unit == unit
    for second in range(duration + 1, duration + 12):
        changed = detector.process(row(second, **{name: (lower + upper) / 2}), CONTEXT)
        if second < duration + 11:
            assert changed == []
    assert changed[0].status == IncidentStatus.RECOVERED


def test_warning_to_error_requires_new_error_duration_and_missing_breaks_timer():
    detector = RuleDetector(enabled_codes={"BTT2-M02"})
    for second in range(4):
        changed = detector.process(row(second, rpm=995), CONTEXT)
    original = changed[0]
    for second in range(4, 7):
        changed = detector.process(row(second, rpm=990), CONTEXT)
        assert changed[0].severity == Severity.WARNING
    error = detector.process(row(7, rpm=990), CONTEXT)[0]
    assert error.severity == Severity.ERROR
    assert error.incident_id == original.incident_id
    for second in range(8, 14):
        detector.process(row(second), CONTEXT)
    detector.process(row(14, rpm=float("nan")), CONTEXT)
    for second in range(15, 25):
        assert detector.process(row(second), CONTEXT) == []
    assert detector.process(row(25), CONTEXT)[0].status == IncidentStatus.RECOVERED


def test_voltage_can_run_without_run_context_and_temperature_upper_during_warmup():
    detector = RuleDetector(enabled_codes={"BTT2-M08", "BTT2-M10", "BTT2-M09"})
    results = []
    for second in range(11):
        results += detector.process(
            row(second, dc_bus_voltage_v=27, motor_housing_temp_c=90)
        )
    assert {item.codes[0] for item in results} == {"BTT2-M08", "BTT2-M10"}


def test_numeric_context_change_interrupts_confirmation():
    detector = RuleDetector(enabled_codes={"BTT2-M02"})
    for second in range(3):
        assert detector.process(row(second, rpm=990), CONTEXT) == []
    # 레시피 변경 후에는 이전 후보 시간을 이어 쓰지 않는다.
    changed_context = {**CONTEXT, "recipe_id": "new"}
    for second in range(3, 6):
        assert detector.process(row(second, rpm=990), changed_context) == []
    assert (
        detector.process(row(6, rpm=990), changed_context)[0].severity == Severity.ERROR
    )


def test_outfeed_occupancy_needs_ready_to_recover():
    detector = RuleDetector(enabled_codes={"BTT2-P04"})
    for second in range(7):
        changed = detector.process(row(second, outfeed_present=True), CONTEXT)
    assert changed[0].severity == Severity.ERROR
    for second in range(7, 11):
        assert (
            detector.process(row(second), {**CONTEXT, "downstream_ready": False}) == []
        )
    for second in (11, 12):
        assert detector.process(row(second), CONTEXT) == []
    assert detector.process(row(13), CONTEXT)[0].status == IncidentStatus.RECOVERED


def test_startup_and_running_stop_use_separate_timers():
    detector = RuleDetector(enabled_codes={"BTT2-M01"})
    context = {**CONTEXT, "run_started_at": T0}
    for second in range(3):
        assert detector.process(row(second, rpm=999), context) == []
    assert detector.process(row(3, rpm=999), context)[0].codes == ["BTT2-M01"]
    stopped = RuleDetector(enabled_codes={"BTT2-M01"})
    stopped.process(row(0), context)
    for second in range(1, 4):
        assert stopped.process(row(second, rpm=100), context) == []
    assert stopped.process(row(4, rpm=100), context)[0].severity == Severity.ERROR


def test_rpm_window_requires_21_valid_samples_and_three_seconds():
    detector = RuleDetector(enabled_codes={"BTT2-M04"})
    for second in range(24):
        changed = detector.process(
            row(second, rpm=1000 if second % 2 else 1070), CONTEXT
        )
        if second < 23:
            assert changed == []
    assert changed[0].severity == Severity.ERROR
    assert "70 rpm" in changed[0].evidence[0].observed


def test_relative_vibration_needs_approved_baseline_and_ten_seconds():
    detector = RuleDetector(enabled_codes={"BTT2-M19"})
    assert detector.process(row(0), CONTEXT) == []
    context = {
        **CONTEXT,
        "vibration_baseline": {
            "de": 0.04,
            "nde": 0.06,
            "approved": True,
            "version": "v1",
        },
    }
    for second in range(1, 12):
        changed = detector.process(
            row(second, de_vibration_rms_g=0.08, nde_vibration_rms_g=0.06), context
        )
        if second < 11:
            assert changed == []
    assert changed[0].severity == Severity.ERROR


def test_all_codes_report_status_and_unknowns_do_not_recover():
    detector = RuleDetector()
    detector.process(row(0))
    assert {item.rule_code for item in detector.last_assessments} == set(CODES)
    statuses = {item.rule_code: item for item in detector.last_assessments}
    assert statuses["BTT2-M02"].severity == Severity.UNKNOWN
    assert statuses["BTT2-P01"].severity == Severity.UNKNOWN
    assert statuses["BTT2-D04"].severity == Severity.UNKNOWN


def test_invalid_assessments_and_policies_do_not_consume_record():
    detector = RuleDetector()
    item = assessment("BTT2-P03", Severity.WARNING)
    with pytest.raises(ValueError, match="중복"):
        detector.process_assessments(row(0), [item, item])
    assert detector.process_assessments(row(0), [item])
    with pytest.raises(ValueError):
        RulePolicy(error_s=-1)
    with pytest.raises(ValueError):
        RuleAssessment("BTT2-invalid", Severity.ERROR)
    with pytest.raises(ValueError):
        RuleDetector(enabled_codes={"BTT2-invalid"})


def test_time_gap_and_suppression_reset_candidates_but_keep_incident():
    code = "BTT2-M08"
    detector = RuleDetector(enabled_codes={code})
    detector.process(row(0, dc_bus_voltage_v=27))
    assert detector.process(row(1, dc_bus_voltage_v=27))
    assert detector.process(row(5)) == []
    for second in range(6, 10):
        detector.process(row(second))
    detector.process(row(10), {"telemetry_valid": False})
    for second in range(11, 21):
        assert detector.process(row(second)) == []
    assert detector.process(row(21))[0].status == IncidentStatus.RECOVERED


def test_transfer_timeout_boundary_late_exit_and_manual_resynchronization():
    detector = RuleDetector(enabled_codes={"BTT2-P01", "BTT2-P06", "BTT2-D04"})
    detector.process(row(0), {**CONTEXT, "tracking_reset": True})
    for second in range(1, 18):
        changed = detector.process(row(second, infeed_present=second == 1), CONTEXT)
        assert not any(item.codes[0] in {"BTT2-P01", "BTT2-P06"} for item in changed)
    changed = detector.process(row(18), CONTEXT)
    assert {item.codes[0] for item in changed} == {"BTT2-P01", "BTT2-P06"}
    changed = detector.process(row(19, outfeed_present=True), CONTEXT)
    assert any(item.codes == ["BTT2-D04"] for item in changed)
    statuses = {item.rule_code: item.severity for item in detector.last_assessments}
    assert statuses["BTT2-P01"] == Severity.UNKNOWN
    changed = detector.process(
        row(20), {**CONTEXT, "tracking_reset": True, "inspection_confirmed": True}
    )
    assert {
        item.codes[0] for item in changed if item.status == IncidentStatus.RECOVERED
    } >= {"BTT2-P01", "BTT2-P06"}


@pytest.mark.parametrize("elapsed", [14, 16])
def test_transfer_normal_boundaries_do_not_make_incidents(elapsed):
    detector = RuleDetector(enabled_codes={"BTT2-P01", "BTT2-P02"})
    detector.process(row(0), {**CONTEXT, "tracking_reset": True})
    for second in range(1, elapsed + 3):
        assert (
            detector.process(
                row(
                    second,
                    infeed_present=second == 1,
                    outfeed_present=second == 1 + elapsed,
                ),
                CONTEXT,
            )
            == []
        )


def test_fast_transfers_window_escalation_and_five_normal_matches_recovery():
    detector = RuleDetector(enabled_codes={"BTT2-P02"})
    detector.process(row(0), {**CONTEXT, "tracking_reset": True})
    entries = {1, 16, 31, 46, 61, 75, 92, 109, 126, 143}
    exits = {14, 29, 44, 59, 74, 90, 107, 124, 141, 158}
    changed_at = {}
    for second in range(1, 159):
        changed = detector.process(
            row(
                second,
                infeed_present=second in entries,
                outfeed_present=second in exits,
            ),
            CONTEXT,
        )
        if changed:
            changed_at[second] = changed[0]
    assert changed_at[14].severity == Severity.WARNING
    assert changed_at[74].severity == Severity.ERROR
    assert changed_at[158].status == IncidentStatus.RECOVERED
    assert changed_at[14].incident_id == changed_at[158].incident_id


def test_infeed_interval_window_and_five_normal_intervals_recovery():
    detector = RuleDetector(enabled_codes={"BTT2-P05"})
    entries = {1, 3, 5, 7, 9, 11, 16, 21, 26, 31, 36}
    changed_at = {}
    for second in range(37):
        changed = detector.process(
            row(second, infeed_present=second in entries), CONTEXT
        )
        if changed:
            changed_at[second] = changed[0]
    assert changed_at[3].severity == Severity.WARNING
    assert changed_at[11].severity == Severity.ERROR
    assert changed_at[36].status == IncidentStatus.RECOVERED


def test_no_infeed_event_has_separate_warning_error_boundaries():
    detector = RuleDetector(enabled_codes={"BTT2-P05"})
    changes = {}
    for second in range(13):
        changes[second] = detector.process(
            row(second, infeed_present=second == 1), CONTEXT
        )
    assert changes[7] == []  # 6초는 경계 안
    assert changes[8][0].severity == Severity.WARNING
    assert changes[11][0].severity == Severity.WARNING
    assert changes[12][0].severity == Severity.ERROR


def test_transfer_trend_uses_nonoverlapping_windows_and_normal_windows_recover():
    detector = RuleDetector(enabled_codes={"BTT2-P07"})
    detector.process(row(0), {**CONTEXT, "tracking_reset": True})
    entries = set(range(1, 47, 5)) | set(range(66, 112, 5))
    exits = set(range(17, 63, 5)) | set(range(81, 127, 5))
    changes = {}
    for second in range(1, 127):
        changed = detector.process(
            row(
                second,
                infeed_present=second in entries,
                outfeed_present=second in exits,
            ),
            CONTEXT,
        )
        if changed:
            changes[second] = changed[0]
    assert changes[37].severity == Severity.WARNING
    assert changes[62].severity == Severity.ERROR
    assert changes[126].status == IncidentStatus.RECOVERED


def test_initial_csv_unknown_tracking_never_invents_transfer_incident():
    detector = RuleDetector(
        enabled_codes={"BTT2-P01", "BTT2-P02", "BTT2-P06", "BTT2-P07"}
    )
    for second in range(40):
        assert (
            detector.process(
                row(
                    second,
                    infeed_present=second in {0, 5, 10},
                    outfeed_present=second in {4, 9, 14},
                ),
                CONTEXT,
            )
            == []
        )


def test_suppression_and_sensor_quality_do_not_create_false_recoveries():
    code = "BTT2-P04"
    detector = RuleDetector(enabled_codes={code})
    for second in range(7):
        detector.process(row(second, outfeed_present=True), CONTEXT)
    for second in range(7, 12):
        assert detector.process(row(second), {**CONTEXT, "planned_hold": True}) == []
    for second in range(12, 15):
        assert (
            detector.process(
                row(second), {**CONTEXT, "invalid_fields": ["outfeed_present"]}
            )
            == []
        )
    for second in (15, 16):
        assert detector.process(row(second), CONTEXT) == []
    assert detector.process(row(17), CONTEXT)[0].status == IncidentStatus.RECOVERED


def test_external_started_at_cannot_bypass_continuity_timer():
    code = "BTT2-M02"
    detector = RuleDetector(enabled_codes={code})
    old_start = T0 - timedelta(seconds=100)
    assert (
        detector.process_assessments(
            row(0), [assessment(code, Severity.ERROR, started_at=old_start)]
        )
        == []
    )
    assert (
        detector.process_assessments(
            row(4), [assessment(code, Severity.ERROR, started_at=old_start)]
        )
        == []
    )


def test_event_recurrence_start_cannot_precede_previous_recovery():
    code = "BTT2-P05"
    detector = RuleDetector(enabled_codes={code})
    first = detector.process_assessments(row(0), [assessment(code, Severity.WARNING)])[
        0
    ]
    detector.process_assessments(row(1), [assessment(code, Severity.NORMAL)])
    recurrent = detector.process_assessments(
        row(2), [assessment(code, Severity.WARNING, started_at=row(1).timestamp)]
    )[0]
    assert recurrent.incident_id != first.incident_id
    assert recurrent.first_detected_at == row(2).timestamp


def test_gap_quality_incident_and_unknown_sensor_are_separate():
    detector = RuleDetector()
    detector.process(row(0), CONTEXT)
    changed = detector.process(row(5, dc_input_current_a=None), CONTEXT)
    assert any(item.codes == ["BTT2-D03"] for item in changed)
    by_code = {item.rule_code: item for item in detector.last_assessments}
    assert by_code["BTT2-M05"].severity == Severity.UNKNOWN
    assert by_code["BTT2-D02"].severity == Severity.WARNING
    assert by_code["BTT2-D02"].evidence[0].observed


def test_unsupported_schema_is_quality_incident_without_machine_incidents():
    detector = RuleDetector()
    invalid = row(0).model_copy(update={"schema_version": "unsupported", "rpm": 0})
    changed = detector.process(invalid, CONTEXT)
    assert {item.codes[0] for item in changed} == {"BTT2-D01"}


def test_invalid_previous_sample_cannot_create_rising_edge():
    detector = RuleDetector(enabled_codes={"BTT2-P05"})
    detector.process(row(0, infeed_present=True), CONTEXT)
    detector.process(row(1), {**CONTEXT, "invalid_fields": ["infeed_present"]})
    assert detector.process(row(2, infeed_present=True), CONTEXT) == []
    detector.process(row(3), CONTEXT)
    assert detector.process(row(4, infeed_present=True), CONTEXT) == []


def test_missing_vibration_baseline_is_reported_as_missing_context():
    detector = RuleDetector()
    detector.process(row(0), CONTEXT)
    statuses = {item.rule_code: item for item in detector.last_assessments}
    assert statuses["BTT2-M19"].context_missing
    assert "BTT2-M19" in statuses["BTT2-D05"].reason


def test_tracking_reset_without_reliable_events_cannot_recover_d04():
    detector = RuleDetector(enabled_codes={"BTT2-D04"})
    detector.process(row(0), CONTEXT)
    changed = detector.process(
        row(1), {**CONTEXT, "tracking_reset": True, "events_reliable": False}
    )
    assert not any(item.status == IncidentStatus.RECOVERED for item in changed)
    assert detector.last_assessments[0].severity == Severity.WARNING


def test_trend_windows_cannot_span_invalid_input_and_resynchronization():
    detector = RuleDetector(enabled_codes={"BTT2-P07"})
    detector.process(row(0), {**CONTEXT, "tracking_reset": True})
    for second in range(1, 38):
        changed = detector.process(
            row(
                second,
                infeed_present=second in {1, 6, 11, 16, 21},
                outfeed_present=second in {17, 22, 27, 32, 37},
            ),
            CONTEXT,
        )
    assert changed[0].severity == Severity.WARNING
    detector.process(row(38), {**CONTEXT, "invalid_fields": ["infeed_present"]})
    detector.process(row(39), {**CONTEXT, "tracking_reset": True})
    for second in range(40, 77):
        changed = detector.process(
            row(
                second,
                infeed_present=second in {40, 45, 50, 55, 60},
                outfeed_present=second in {56, 61, 66, 71, 76},
            ),
            CONTEXT,
        )
    assert changed[0].severity == Severity.WARNING
