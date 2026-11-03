"""telemetry 테이블(#63): 대량 저장, 같은 시각 중복 건너뛰기, 구간 조회."""

from datetime import timedelta

from weeing_weeing.contracts import TelemetryRecord


def _records(sample_rows) -> list[TelemetryRecord]:
    return [TelemetryRecord(**row) for row in sample_rows]


def test_save_many_and_query_range(telemetry, sample_rows):
    records = _records(sample_rows)
    assert telemetry.save_many(records) == len(records)

    first, last = records[0], records[-1]
    got = telemetry.between(first.asset_id, first.timestamp, last.timestamp)
    assert got == records[:-1]  # 끝 시각은 포함하지 않는다
    assert telemetry.latest(first.asset_id) == last


def test_replay_does_not_duplicate(telemetry, sample_rows):
    records = _records(sample_rows)
    telemetry.save_many(records[:10])

    assert telemetry.save_many(records) == len(records) - 10
    assert telemetry.save_many(records) == 0
    end = records[-1].timestamp + timedelta(seconds=1)
    assert len(
        telemetry.between(records[0].asset_id, records[0].timestamp, end)
    ) == len(records)


def test_missing_values_stay_none(telemetry, sample_rows):
    row = sample_rows[0] | {"dc_input_current_a": "", "motor_housing_temp_c": ""}
    record = TelemetryRecord(**row)
    telemetry.save_many([record])

    assert telemetry.latest(record.asset_id) == record
    assert telemetry.latest(record.asset_id).dc_input_current_a is None


def test_large_batch_is_split(telemetry, sample_rows, monkeypatch):
    from weeing_weeing.db import telemetry as module

    monkeypatch.setattr(module, "BATCH", 7)
    records = _records(sample_rows)
    assert telemetry.save_many(records) == len(records)


def test_unknown_asset_is_empty(telemetry, sample_rows):
    record = _records(sample_rows)[0]
    end = record.timestamp + timedelta(hours=1)
    assert telemetry.between("없는-설비", record.timestamp, end) == []
    assert telemetry.latest("없는-설비") is None


def test_latest_can_narrow_by_process(telemetry, sample_rows):
    first = _records(sample_rows)[0]
    other = first.model_copy(
        update={"process_id": "OTHER", "timestamp": first.timestamp + timedelta(1)}
    )
    telemetry.save_many([first, other])

    assert telemetry.latest(first.asset_id) == other
    assert telemetry.latest(first.asset_id, process_id=first.process_id) == first
