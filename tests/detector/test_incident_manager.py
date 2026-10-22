"""CSV 센서값과 가짜 룰 판정으로 사건 수명주기를 검증한다.

발생·회복 시점은 테스트 입력이며, 실제 룰 임계값이나 지속 조건을 뜻하지 않는다.
"""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import (
    Incident,
    IncidentStatus,
    SensorEvidence,
    Severity,
    TelemetryRecord,
)
from weeing_weeing.detector.incident_manager import IncidentManager

CODE = "BTT2-P03"


@pytest.fixture
def records(sample_rows):
    return [TelemetryRecord.model_validate(row) for row in sample_rows]


@pytest.fixture
def manager():
    return IncidentManager()


@pytest.fixture
def evidence(records):
    return [
        SensorEvidence(
            field="infeed_present",
            value=records[23].infeed_present,
            threshold="테스트용 가짜 확정 판정",
            observed="CSV 20~23초 입구 감지",
        )
    ]


def test_confirm_records_identifiers_timestamps_and_evidence(
    manager, records, evidence
):
    incident = manager.confirm(
        records[23],
        CODE,
        severity=Severity.ERROR,
        first_detected_at=records[20].timestamp,
        evidence=evidence,
    )

    assert incident.incident_id
    assert incident.process_id == records[23].process_id
    assert incident.asset_id == records[23].asset_id
    assert incident.codes == [CODE]
    assert incident.status == IncidentStatus.OPEN
    assert incident.severity == Severity.ERROR
    assert incident.first_detected_at == records[20].timestamp
    assert incident.confirmed_at == records[23].timestamp
    assert incident.last_detected_at == records[23].timestamp
    assert incident.recovered_at is None
    assert incident.evidence == evidence
    assert manager.all_incidents() == [incident]


def test_confirm_defaults_candidate_start_to_confirmation_time(manager, records):
    incident = manager.confirm(records[23], CODE, severity=Severity.ERROR)
    assert incident.first_detected_at == incident.confirmed_at == records[23].timestamp


def test_repeated_confirmation_keeps_one_incident_and_original_times(manager, records):
    first = manager.confirm(
        records[23],
        CODE,
        severity=Severity.WARNING,
        first_detected_at=records[20].timestamp,
    )
    for record in records[24:30]:
        latest = manager.confirm(record, CODE, severity=Severity.ERROR)

    assert latest.incident_id == first.incident_id
    assert latest.first_detected_at == first.first_detected_at
    assert latest.confirmed_at == first.confirmed_at
    assert latest.last_detected_at == records[29].timestamp
    assert latest.severity == Severity.ERROR
    assert len(manager.all_incidents()) == 1


def test_update_preserves_omitted_fields_and_replaces_supplied_fields(
    manager, records, evidence
):
    original = manager.confirm(
        records[23], CODE, severity=Severity.WARNING, evidence=evidence, direction="H"
    )
    unchanged = manager.update(records[24], CODE)
    assert unchanged.evidence == original.evidence
    assert unchanged.severity == original.severity
    assert unchanged.direction == "H"

    replacement = [SensorEvidence(field="rpm", value=records[25].rpm, unit="rpm")]
    changed = manager.update(
        records[25], CODE, severity=Severity.ERROR, evidence=replacement, direction="L"
    )
    assert changed.evidence == replacement
    assert changed.severity == Severity.ERROR
    assert changed.direction == "L"
    assert changed.incident_id == original.incident_id
    assert manager.update(records[26], CODE, evidence=[]).evidence == []


def test_recovery_preserves_last_abnormal_time_and_remains_unclosed(manager, records):
    manager.confirm(records[23], CODE, severity=Severity.ERROR)
    manager.update(records[29], CODE)
    recovered = manager.recover(records[30], CODE)

    assert recovered.status == IncidentStatus.RECOVERED
    assert recovered.recovered_at == records[30].timestamp
    assert recovered.last_detected_at == records[29].timestamp
    assert (
        manager.find_active(records[30].process_id, records[30].asset_id, CODE) is None
    )
    assert manager.all_incidents() == [recovered]
    # active_incidents는 기존 Detector 계약대로 미종결 사건을 뜻한다.
    assert manager.active_incidents() == [recovered]


def test_recurrence_creates_new_id_and_keeps_recovered_history(manager, records):
    first = manager.confirm(records[23], CODE, severity=Severity.ERROR)
    recovered = manager.recover(records[30], CODE)
    second = manager.confirm(records[40], CODE, severity=Severity.WARNING)

    assert first.incident_id != second.incident_id
    assert second.status == IncidentStatus.OPEN
    assert second.first_detected_at == records[40].timestamp
    assert manager.all_incidents() == [recovered, second]
    assert (
        manager.find_active(records[40].process_id, records[40].asset_id, CODE)
        == second
    )


@pytest.mark.parametrize("dimension", ["process_id", "asset_id", "rule_code"])
def test_incidents_are_separate_by_process_asset_and_rule(manager, records, dimension):
    first = manager.confirm(records[23], CODE, severity=Severity.ERROR)
    row = records[23].model_dump()
    code = CODE
    if dimension == "rule_code":
        code = "BTT2-P04"
    else:
        row[dimension] = "OTHER"
    other_record = TelemetryRecord.model_validate(row)
    second = manager.confirm(other_record, code, severity=Severity.ERROR)

    assert first.incident_id != second.incident_id
    manager.recover(records[30], CODE)
    assert (
        manager.find_active(other_record.process_id, other_record.asset_id, code)
        == second
    )


@pytest.mark.parametrize("method", ["update", "recover"])
def test_missing_incident_is_rejected_without_creating_history(
    manager, records, method
):
    with pytest.raises(KeyError, match="진행 중인 사건이 없음"):
        getattr(manager, method)(records[23], CODE)
    assert manager.all_incidents() == []


@pytest.mark.parametrize("method", ["update", "recover"])
def test_recovered_incident_cannot_be_updated_or_recovered_again(
    manager, records, method
):
    manager.confirm(records[23], CODE, severity=Severity.ERROR)
    recovered = manager.recover(records[30], CODE)
    with pytest.raises(KeyError):
        getattr(manager, method)(records[31], CODE)
    assert manager.all_incidents() == [recovered]


@pytest.mark.parametrize("method", ["confirm", "update", "recover"])
def test_out_of_order_input_leaves_existing_incident_unchanged(
    manager, records, method
):
    original = manager.confirm(records[23], CODE, severity=Severity.ERROR)
    kwargs = {"severity": Severity.WARNING} if method == "confirm" else {}
    with pytest.raises(ValueError, match="이전 입력"):
        getattr(manager, method)(records[22], CODE, **kwargs)
    assert manager.all_incidents() == [original]
    assert manager.find_active(original.process_id, original.asset_id, CODE) == original


@pytest.mark.parametrize("invalid_start", ["naive", "future"])
def test_invalid_candidate_start_does_not_create_incident(
    manager, records, invalid_start
):
    at = records[23].timestamp
    start = (
        at.replace(tzinfo=None)
        if invalid_start == "naive"
        else at + timedelta(seconds=1)
    )
    with pytest.raises(ValueError):
        manager.confirm(
            records[23], CODE, severity=Severity.ERROR, first_detected_at=start
        )
    assert manager.all_incidents() == []


def test_unknown_rule_does_not_create_incident(manager, records):
    with pytest.raises(ValidationError, match="정의되지 않은 코드"):
        manager.confirm(records[23], "NOT-A-RULE", severity=Severity.ERROR)
    assert manager.all_incidents() == []


def test_duplicate_timestamp_does_not_create_another_incident(manager, records):
    original = manager.confirm(records[23], CODE, severity=Severity.ERROR)
    assert manager.confirm(records[23], CODE, severity=Severity.ERROR) == original
    assert manager.all_incidents() == [original]


def test_input_and_returned_objects_cannot_mutate_stored_incident(
    manager, records, evidence
):
    created = manager.confirm(
        records[23], CODE, severity=Severity.ERROR, evidence=evidence
    )
    evidence[0].note = "입력값 변경"
    created.codes.clear()
    created.evidence[0].note = "반환값 변경"
    stored = manager.all_incidents()[0]
    assert stored.codes == [CODE]
    assert stored.evidence[0].note is None

    snapshot = stored.model_copy(deep=True)
    copies = [
        manager.find_active(stored.process_id, stored.asset_id, CODE),
        manager.all_incidents()[0],
        manager.active_incidents()[0],
        manager.update(records[23], CODE),
    ]
    for copy in copies:
        copy.evidence[0].note = "외부 변경"
        copy.status = IncidentStatus.CLOSED
    assert manager.all_incidents() == [snapshot]


def test_json_preserves_sensor_evidence_and_recovery_state(manager, records, evidence):
    manager.confirm(records[23], CODE, severity=Severity.ERROR, evidence=evidence)
    recovered = manager.recover(records[30], CODE)
    assert Incident.model_validate_json(recovered.model_dump_json()) == recovered


def test_managers_do_not_share_memory(records):
    first, second = IncidentManager(), IncidentManager()
    first.confirm(records[23], CODE, severity=Severity.ERROR)
    assert second.all_incidents() == []


@pytest.mark.parametrize("index", [22, 23, 29, 30])
def test_confirmation_at_or_before_recovery_cannot_create_false_recurrence(
    manager, records, index
):
    manager.confirm(records[23], CODE, severity=Severity.ERROR)
    recovered = manager.recover(records[30], CODE)

    with pytest.raises(ValueError, match="회복 시각"):
        manager.confirm(records[index], CODE, severity=Severity.ERROR)

    assert manager.all_incidents() == [recovered]
    assert manager.find_active(recovered.process_id, recovered.asset_id, CODE) is None
    recurrence = manager.confirm(records[31], CODE, severity=Severity.WARNING)
    assert recurrence.incident_id != recovered.incident_id


@pytest.mark.parametrize("index", [29, 30])
def test_recurrence_candidate_cannot_start_before_or_at_previous_recovery(
    manager, records, index
):
    manager.confirm(records[23], CODE, severity=Severity.ERROR)
    recovered = manager.recover(records[30], CODE)

    with pytest.raises(ValueError, match="회복 시각"):
        manager.confirm(
            records[40],
            CODE,
            severity=Severity.ERROR,
            first_detected_at=records[index].timestamp,
        )
    assert manager.all_incidents() == [recovered]


@pytest.mark.parametrize("dimension", ["process_id", "asset_id", "rule_code"])
def test_recovery_time_does_not_block_another_process_asset_or_rule(
    manager, records, dimension
):
    manager.confirm(records[23], CODE, severity=Severity.ERROR)
    manager.recover(records[30], CODE)
    row = records[23].model_dump()
    code = CODE
    if dimension == "rule_code":
        code = "BTT2-P04"
    else:
        row[dimension] = "OTHER"

    separate = manager.confirm(
        TelemetryRecord.model_validate(row), code, severity=Severity.ERROR
    )
    assert separate.status == IncidentStatus.OPEN
    assert len(manager.all_incidents()) == 2


def test_second_recovery_replaces_the_recovery_time_boundary(manager, records):
    manager.confirm(records[23], CODE, severity=Severity.ERROR)
    manager.recover(records[30], CODE)
    manager.confirm(records[31], CODE, severity=Severity.ERROR)
    manager.recover(records[40], CODE)
    history = manager.all_incidents()

    with pytest.raises(ValueError, match="회복 시각"):
        manager.confirm(records[35], CODE, severity=Severity.ERROR)
    assert manager.all_incidents() == history
