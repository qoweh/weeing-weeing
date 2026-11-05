import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import SCHEMA_VERSION, TelemetryRecord
from weeing_weeing.contracts.telemetry import COLUMNS, TelemetryProvenance


def test_sample_csv_matches_contract(sample_rows):
    assert len(sample_rows) == 60
    assert tuple(sample_rows[0].keys()) == COLUMNS

    records = [TelemetryRecord.model_validate(row) for row in sample_rows]

    assert all(r.schema_version == SCHEMA_VERSION for r in records)
    assert all(r.timestamp.tzinfo is not None for r in records)
    # 원본은 전류·온도가 전부 비어 있다(정의서 9절). 0이 아니라 None이어야 한다.
    assert all(r.dc_input_current_a is None for r in records)
    assert all(r.motor_housing_temp_c is None for r in records)
    # 입구 t20~t29 연속 true 구간(장기 점유 시연 구간, 정의서 10절)
    assert all(records[i].infeed_present for i in range(20, 30))
    assert not records[30].infeed_present


def test_rejects_naive_timestamp(sample_rows):
    row = sample_rows[0] | {"timestamp": "2026-10-05T14:00:00"}
    with pytest.raises(ValidationError):
        TelemetryRecord.model_validate(row)


def test_rejects_unknown_column(sample_rows):
    row = sample_rows[0] | {"belt_speed": "0.25"}
    with pytest.raises(ValidationError):
        TelemetryRecord.model_validate(row)


def test_provenance_is_separate_from_fifteen_field_record(sample_rows):
    record = TelemetryRecord.model_validate(sample_rows[0])
    assert set(record.model_dump()) == set(COLUMNS)
    assert TelemetryProvenance().origin == "UNKNOWN"
    profile = TelemetryProvenance(origin="SIMULATION", expected_interval_s=1)
    assert TelemetryProvenance.model_validate_json(profile.model_dump_json()) == profile


@pytest.mark.parametrize(
    "values",
    [
        {"origin": "guess"},
        {"expected_interval_s": 0},
        {"expected_interval_s": -1},
        {"expected_interval_s": float("nan")},
        {"expected_interval_s": float("inf")},
        {"expected_interval_s": 61},
        {"api_key": "fake-only"},
    ],
)
def test_provenance_rejects_invalid_fields(values):
    with pytest.raises(ValidationError):
        TelemetryProvenance(**values)
