import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weeing_weeing.contracts import TelemetryRecord
from weeing_weeing.contracts.telemetry import COLUMNS
from weeing_weeing.detector.interface import (
    HistoryDetector,
    HistoryError,
    HistoryReader,
    RuleDetector,
)
from weeing_weeing.ingest.interface import (
    CsvJsonSource,
    CsvTelemetryError,
    JsonTelemetryInput,
    TelemetryInputError,
    parse_telemetry_json,
    replay_json,
)

T0 = datetime(2026, 10, 5, tzinfo=timezone(timedelta(hours=9)))


def payload(second=0, **changes):
    data = dict(
        record_id=f"row-{second}",
        timestamp=(T0 + timedelta(seconds=second)).isoformat(),
        process_id="process",
        asset_id="asset",
        schema_version="3.0.0",
        infeed_present=False,
        outfeed_present=False,
        rpm=1015,
        dc_input_current_a=None,
        dc_bus_voltage_v=24,
        motor_housing_temp_c=65,
        de_vibration_rms_g=0.06,
        de_kurtosis=5,
        nde_vibration_rms_g=0.055,
        nde_kurtosis=4,
    )
    data.update(changes)
    return data


def test_normal_and_abnormal_delivered_once_with_context_and_values():
    calls = []
    context = {"run_cmd": True}
    receiver = JsonTelemetryInput(lambda record, ctx: calls.append((record, ctx)))
    for rpm in (1015, -500):
        data = payload(rpm=rpm, motor_housing_temp_c=None)
        receiver.receive(json.dumps(data).encode(), context)
        assert calls[-1][0].model_dump(mode="json") == data
        assert calls[-1][1] is context
        assert len(calls[-1][0].model_dump()) == 15
    assert len(calls) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"rpm": "1015"},
        {"rpm": True},
        {"rpm": None},
        {"rpm": float("inf")},
        {"rpm": float("nan")},
        {"infeed_present": "false"},
        {"outfeed_present": 0},
        {"dc_input_current_a": ""},
        {"schema_version": "2.0.0"},
        {"record_id": "  "},
        {"process_id": ""},
        {"asset_id": 1},
        {"timestamp": "2026-10-05T00:00:00"},
        {"timestamp": 123},
        {"extra": "secret"},
        {"rpm": 10**400},
    ],
)
def test_invalid_fields_never_reach_handler_and_next_valid_is_accepted(changes):
    calls = []
    receiver = JsonTelemetryInput(lambda *args: calls.append(args))
    with pytest.raises(TelemetryInputError) as error:
        receiver.receive(json.dumps(payload(**changes)))
    assert "secret" not in str(error.value)
    assert calls == []
    receiver.receive(json.dumps(payload()))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "message",
    [
        "{",
        "[]",
        "{}",
        "{} {}",
        b"\xff",
        '"secret"',
        '{"rpm":1,"rpm":2}',
        json.dumps({k: v for k, v in payload().items() if k != "dc_input_current_a"}),
        json.dumps(payload()).replace("1015", "1e999"),
        "[" * 2000 + "]" * 2000,
        "\ud800",
    ],
)
def test_malformed_messages(message):
    with pytest.raises(TelemetryInputError):
        parse_telemetry_json(message)


def test_size_and_configuration():
    message = json.dumps(payload(asset_id="설비"), ensure_ascii=False)
    size = len(message.encode())
    assert parse_telemetry_json(message, max_message_bytes=size)
    with pytest.raises(TelemetryInputError):
        parse_telemetry_json(message, max_message_bytes=size - 1)
    with pytest.raises(TelemetryInputError):
        parse_telemetry_json(" " * 65537)
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            JsonTelemetryInput(lambda *_: None, max_message_bytes=invalid)


def test_duplicate_key_in_complete_object_is_rejected_without_payload_leak():
    message = json.dumps(payload())[:-1] + ', "record_id": "secret"}'
    with pytest.raises(TelemetryInputError, match="Duplicate") as error:
        parse_telemetry_json(message)
    assert "secret" not in str(error.value)


def test_handler_failure_is_not_wrapped_or_retried():
    calls = []
    failure = RuntimeError("sink failure")

    def fail(*args):
        calls.append(args)
        raise failure

    receiver = JsonTelemetryInput(fail)
    with pytest.raises(RuntimeError) as error:
        receiver.receive(json.dumps(payload()))
    assert error.value is failure
    assert len(calls) == 1


def write_csv(path, header=COLUMNS, rows=None):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        for data in rows if rows is not None else [payload()]:
            writer.writerow([data[name] for name in header])


def test_csv_roundtrip_streaming_and_failure_line(tmp_path):
    path = tmp_path / "input.csv"
    samples = [payload(0), payload(0.5, rpm=1040)]
    write_csv(path, rows=samples)
    assert [parse_telemetry_json(m) for m in CsvJsonSource(path)] == [
        TelemetryRecord.model_validate(data) for data in samples
    ]
    write_csv(path, rows=[payload(), payload(1, rpm="secret")])
    source = iter(CsvJsonSource(path))
    assert parse_telemetry_json(next(source))
    with pytest.raises(CsvTelemetryError, match="line 3") as error:
        next(source)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "header", [COLUMNS[:-1], COLUMNS + ("extra",), COLUMNS[:-1] + ("rpm",), ()]
)
def test_csv_header(tmp_path, header):
    path = tmp_path / "input.csv"
    write_csv(path, header, rows=[])
    with pytest.raises(CsvTelemetryError, match="line 1"):
        list(CsvJsonSource(path))


@pytest.mark.parametrize(
    "tail", ["a,b\n", ",".join([""] * 15), '"unterminated', "\xff"]
)
def test_csv_invalid_rows(tmp_path, tail):
    path = tmp_path / "input.csv"
    path.write_bytes((",".join(COLUMNS) + "\n").encode() + tail.encode("latin1"))
    with pytest.raises(CsvTelemetryError, match="line"):
        list(CsvJsonSource(path))


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.sleeps.append(duration)
        self.now += duration


@pytest.mark.parametrize("interval", [0, 0.5, 1.25])
def test_replay_deadlines_and_backpressure(interval):
    clock = Clock()
    calls = []

    def receive(message):
        calls.append((message, clock.now))
        clock.now += 0.2 if message != "b" else 2

    assert (
        replay_json(
            "abcd", receive, interval, monotonic=clock.monotonic, sleep=clock.sleep
        )
        == 4
    )
    starts = [t for _, t in calls]
    assert starts == pytest.approx(
        [
            0,
            max(interval, 0.2),
            max(interval, 0.2) + max(interval, 2),
            max(interval, 0.2) + max(interval, 2) + max(interval, 0.2),
        ]
    )
    assert [m for m, _ in calls] == list("abcd")


@pytest.mark.parametrize(
    "interval", [-1, float("nan"), float("inf"), -float("inf"), True, "0.5"]
)
def test_invalid_interval(interval):
    with pytest.raises(ValueError):
        replay_json([], lambda _: None, interval)


def test_replay_stops_at_first_failure():
    pulled = []

    def messages():
        for i in range(3):
            pulled.append(i)
            yield i

    def receive(message):
        if message == 1:
            raise RuntimeError

    with pytest.raises(RuntimeError):
        replay_json(messages(), receive, 0)
    assert pulled == [0, 1]


def test_half_second_numeric_rule_and_history_match_direct_path(tmp_path):
    direct = RuleDetector(enabled_codes={"BTT2-M10"})
    with HistoryDetector(tmp_path, enabled_codes={"BTT2-M10"}) as history:
        receiver = JsonTelemetryInput(history.process)
        for tick in range(49):
            second = tick / 2
            data = payload(second, motor_housing_temp_c=90 if second < 12 else 65)
            expected = direct.process(
                TelemetryRecord.model_validate(data), {"run_cmd": True}
            )
            actual = receiver.receive(json.dumps(data), {"run_cmd": True})
            assert [x.model_dump(exclude={"incident_id"}) for x in actual] == [
                x.model_dump(exclude={"incident_id"}) for x in expected
            ]
            if tick < 20:
                assert actual == []
            if tick == 20:
                assert actual[0].confirmed_at == T0 + timedelta(seconds=10)
    reader = HistoryReader(history.run_path)
    assert reader.validate()
    saved = list(reader.telemetry(reader.list_incidents()[0]))
    phases = [entry["annotation"]["collection_phase"] for entry in saved]
    assert phases[:20] == ["candidate"] * 20
    assert "recovery_wait" in phases
    assert phases[-1] == "recovered"
    assert len(saved) == 45  # 0..22 seconds inclusive, 0.5-second samples


def test_history_failure_still_forbids_reuse(tmp_path):
    with pytest.raises(HistoryError):
        with HistoryDetector(tmp_path, enabled_codes={"BTT2-M10"}) as history:
            receiver = JsonTelemetryInput(history.process)
            receiver.receive(json.dumps(payload()))
            # Conflicting ID fails in history after successful wire validation.
            with pytest.raises(ValueError):
                receiver.receive(json.dumps(payload(1, record_id="row-0")))
            with pytest.raises(HistoryError):
                receiver.receive(json.dumps(payload(2)))


def test_storage_failure_is_not_retried_and_poisoned_history_rejects_next(
    tmp_path, monkeypatch
):
    history = HistoryDetector(tmp_path, enabled_codes={"BTT2-M10"})
    calls = []

    def fail_save():
        calls.append(1)
        raise OSError("disk failure")

    # Inject a persistence failure at the existing history boundary.
    monkeypatch.setattr(history, "_save_manifest", fail_save)
    receiver = JsonTelemetryInput(history.process)
    with pytest.raises(OSError):
        receiver.receive(json.dumps(payload()))
    assert len(calls) == 2  # initial write, then history's failed-state marker
    count = len(calls)
    with pytest.raises(HistoryError):
        receiver.receive(json.dumps(payload(1)))
    assert len(calls) == count


def test_real_v4_direct_and_json_history_equivalence(tmp_path):
    path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "telemetry"
        / "battery_tray_transfer_5min_warning_error_v4.csv"
    )
    if not path.is_file():
        pytest.skip("Actual v4 CSV is unavailable; synthetic coverage remains active")
    direct = RuleDetector()
    count = 0
    changes = 0
    origin = None
    with HistoryDetector(tmp_path) as history:
        receiver = JsonTelemetryInput(history.process)
        with path.open(encoding="utf-8-sig", newline="") as file:
            for index, (raw, message) in enumerate(
                zip(csv.DictReader(file), CsvJsonSource(path), strict=True)
            ):
                record = TelemetryRecord.model_validate(raw)
                if origin is None:
                    origin = record.timestamp
                elif index == 1:
                    assert (record.timestamp - origin).total_seconds() == 1
                assert parse_telemetry_json(message) == record
                context = {
                    "run_cmd": True,
                    "events_reliable": True,
                    "downstream_ready": True,
                    "tracking_reset": index == 0
                    and not record.infeed_present
                    and not record.outfeed_present,
                }
                expected = direct.process(record, context)
                actual = receiver.receive(message, context)
                assert [x.model_dump(exclude={"incident_id"}) for x in actual] == [
                    x.model_dump(exclude={"incident_id"}) for x in expected
                ]
                count += 1
                changes += len(actual)
    assert count == 300
    assert changes == 372
    reader = HistoryReader(history.run_path)
    assert reader.validate()
    ids = reader.list_incidents()
    assert len(ids) == 3
    m10 = next(i for i in ids if reader.incident(i).codes == ["BTT2-M10"])
    entries = list(reader.telemetry(m10))
    assert len(entries) == 67
    incident = reader.incident(m10)
    assert (incident.first_detected_at - origin).total_seconds() == 81
    assert (incident.confirmed_at - origin).total_seconds() == 91
    assert (incident.last_detected_at - origin).total_seconds() == 136
    assert (incident.recovered_at - origin).total_seconds() == 147
    escalation = next(e for e in reader.events(m10) if e["kind"] == "escalated")
    assert (
        datetime.fromisoformat(escalation["timestamp"]) - origin
    ).total_seconds() == 109
    waiting = [
        e for e in entries if e["annotation"]["collection_phase"] == "recovery_wait"
    ]
    assert len(waiting) == 10
    assert [
        (datetime.fromisoformat(e["record"]["timestamp"]) - origin).total_seconds()
        for e in waiting
    ] == list(range(137, 147))
