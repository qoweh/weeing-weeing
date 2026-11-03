"""P03 실제 판정과 Manager·JSON 연결을 검증한다."""

from datetime import timedelta

import pytest

from weeing_weeing.contracts import Incident, IncidentStatus, Severity, TelemetryRecord
from weeing_weeing.detector.interface import P03Detector
from weeing_weeing.detector.p03 import P03RuleEvaluator

RUN = {"run_cmd": True}


def sample(sample_rows, second, *, infeed=None, asset=None):
    record = TelemetryRecord.model_validate(sample_rows[second])
    updates = {}
    if infeed is not None:
        updates["infeed_present"] = infeed
    if asset is not None:
        updates["asset_id"] = asset
    return record.model_copy(update=updates)


def test_csv_real_p03_lifecycle_and_json(sample_rows):
    detector = P03Detector()
    changes = {}
    for second in range(20, 33):
        changes[second] = detector.process(sample(sample_rows, second), RUN)
    warning = changes[24][0]
    error = changes[26][0]
    recovered = changes[32][0]
    assert not any(changes[t] for t in range(20, 24))
    assert warning.codes == ["BTT2-P03"]
    assert warning.severity == Severity.WARNING
    assert error.severity == Severity.ERROR
    assert warning.incident_id == error.incident_id == recovered.incident_id
    assert warning.first_detected_at == sample(sample_rows, 20).timestamp
    assert warning.confirmed_at == sample(sample_rows, 24).timestamp
    assert recovered.confirmed_at == warning.confirmed_at
    assert recovered.last_detected_at == sample(sample_rows, 29).timestamp
    assert recovered.recovered_at == sample(sample_rows, 32).timestamp
    assert changes[30] == changes[31] == []
    assert recovered.evidence == changes[29][0].evidence
    assert recovered.status == IncidentStatus.RECOVERED
    assert [item.field for item in error.evidence] == ["infeed_present"]
    assert Incident.model_validate_json(recovered.model_dump_json()) == recovered
    # Detector 계약의 active는 회복된 사건도 포함한다.
    assert detector.active_incidents() == [recovered]


def test_duplicates_do_not_update_or_advance_recovery(sample_rows):
    detector = P03Detector()
    for second in range(20, 31):
        row = sample(sample_rows, second)
        detector.process(row, RUN)
        assert detector.process(row, RUN) == []
    assert detector.process(sample(sample_rows, 31), RUN) == []
    assert detector.process(sample(sample_rows, 32), RUN)[0].recovered_at is not None


@pytest.mark.parametrize(
    "context", [{}, {"run_cmd": False}, {**RUN, "telemetry_valid": False}]
)
def test_unknown_or_suppressed_breaks_recovery_without_closing(sample_rows, context):
    detector = P03Detector()
    for second in range(20, 31):
        detector.process(sample(sample_rows, second), RUN)
    assert detector.process(sample(sample_rows, 31), context) == []
    assert detector.process(sample(sample_rows, 32), RUN) == []
    assert detector.process(sample(sample_rows, 33), RUN) == []
    recovered = detector.process(sample(sample_rows, 34), RUN)[0]
    assert recovered.status == IncidentStatus.RECOVERED
    assert recovered.last_detected_at == sample(sample_rows, 29).timestamp


def test_gap_breaks_candidate_and_recovery(sample_rows):
    detector = P03Detector()
    for second in range(20, 24):
        assert detector.process(sample(sample_rows, second), RUN) == []
    # 공백 이후 t26부터 후보를 새로 측정한다.
    for second in range(26, 30):
        assert detector.process(sample(sample_rows, second), RUN) == []
    warning = detector.process(sample(sample_rows, 30, infeed=True), RUN)[0]
    assert warning.first_detected_at == sample(sample_rows, 26).timestamp
    detector.process(sample(sample_rows, 31), RUN)
    assert detector.process(sample(sample_rows, 35, infeed=False), RUN) == []
    assert detector.process(sample(sample_rows, 36, infeed=False), RUN) == []
    assert (
        detector.process(sample(sample_rows, 37, infeed=False), RUN)[0].status
        == IncidentStatus.RECOVERED
    )


def test_error_stays_error_after_short_false_and_recurrence_gets_new_id(sample_rows):
    detector = P03Detector()
    for second in range(20, 31):
        changes = detector.process(sample(sample_rows, second), RUN)
        if second == 26:
            first_id = changes[0].incident_id
    for second in range(31, 36):
        changes = detector.process(sample(sample_rows, second, infeed=True), RUN)
    assert changes[0].severity == Severity.ERROR
    assert changes[0].incident_id == first_id
    for second in range(36, 39):
        changes = detector.process(sample(sample_rows, second, infeed=False), RUN)
    assert changes[0].status == IncidentStatus.RECOVERED
    for second in range(39, 44):
        changes = detector.process(sample(sample_rows, second, infeed=True), RUN)
    assert changes[0].incident_id != first_id
    assert changes[0].severity == Severity.WARNING


def test_reverse_time_breaks_timer_and_assets_are_independent(sample_rows):
    detector = P03Detector()
    for second in range(20, 24):
        detector.process(sample(sample_rows, second), RUN)
        assert detector.process(sample(sample_rows, second, asset="other"), RUN) == []
    with pytest.raises(ValueError):
        detector.process(sample(sample_rows, 22), RUN)
    assert detector.process(sample(sample_rows, 24), RUN) == []
    assert (
        detector.process(sample(sample_rows, 24, asset="other"), RUN)[0].severity
        == Severity.WARNING
    )


def test_decision_keeps_original_record_and_uses_elapsed_time(sample_rows):
    evaluator = P03RuleEvaluator()
    initial = sample(sample_rows, 20)
    for tick in range(8):
        row = initial.model_copy(
            update={
                "record_id": f"half-second-{tick}",
                "timestamp": initial.timestamp + timedelta(seconds=tick / 2),
            }
        )
        decisions = evaluator.evaluate(row, run_cmd=True)
        if tick <= 6:
            assert decisions == []
    assert decisions[0].record == row
    assert decisions[0].first_detected_at == initial.timestamp
    assert decisions[0].action == "confirm"
