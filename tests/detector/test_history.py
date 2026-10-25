"""Round-trip, collection boundaries, fail-stop and file integrity regressions."""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weeing_weeing.contracts import (
    IncidentStatus,
    SensorEvidence,
    Severity,
    TelemetryRecord,
)
from weeing_weeing.detector.interface import (
    HistoryConfig,
    HistoryDetector,
    HistoryError,
    HistoryReader,
    RuleAssessment,
    RuleDetector,
    RulePolicy,
)

CODE = "BTT2-M10"
OTHER = "BTT2-M08"
T0 = datetime(2026, 10, 5, tzinfo=timezone(timedelta(hours=9)))
ROOT = Path(__file__).resolve().parents[2]


def row(second, **changes):
    data = dict(
        record_id=f"row-{second}",
        timestamp=T0 + timedelta(seconds=second),
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
    return TelemetryRecord(**data)


def items(severity, codes=(CODE,)):
    return [
        RuleAssessment(
            code, severity, evidence=[SensorEvidence(field="rpm", value=990)]
        )
        for code in codes
    ]


def collector(tmp_path, **kwargs):
    return HistoryDetector(
        tmp_path, enabled_codes={CODE}, policies={CODE: RulePolicy(2, 1, 2)}, **kwargs
    )


@pytest.mark.parametrize(
    "sequence",
    [[Severity.NORMAL] * 5, [Severity.WARNING, Severity.NORMAL, Severity.NORMAL]],
)
def test_unconfirmed_or_normal_has_no_incident_files(tmp_path, sequence):
    with collector(tmp_path) as detector:
        for i, severity in enumerate(sequence):
            detector.process(row(i), assessments=items(severity))
    reader = HistoryReader(detector.run_path)
    assert reader.list_incidents() == []
    assert reader.validate()


def test_full_lifecycle_and_original_rows_without_manager_changes(tmp_path):
    samples = [row(i, motor_housing_temp_c=90 if i < 6 else 65) for i in range(12)]
    sequence = (
        [Severity.WARNING] * 3
        + [Severity.ERROR] * 2
        + [Severity.WARNING]
        + [Severity.NORMAL] * 3
        + [Severity.WARNING] * 3
    )
    with collector(tmp_path) as detector:
        changes = [
            detector.process(sample, assessments=items(severity))
            for sample, severity in zip(samples, sequence)
        ]
        assert changes[6:8] == [[], []]  # manager does not emit recovery wait rows
    reader = HistoryReader(detector.run_path)
    assert reader.validate()
    first = changes[2][0].incident_id
    assert changes[4][0].incident_id == first
    assert changes[5][0].severity == Severity.ERROR  # no new downgrade policy
    assert changes[11][0].incident_id != first
    saved = list(reader.telemetry(first))
    assert [entry["record"] for entry in saved] == [
        r.model_dump(mode="json") for r in samples[:9]
    ]
    assert all(
        len(entry["record"]) == 15 and entry["incident_id"] == first for entry in saved
    )
    assert [e["annotation"]["collection_phase"] for e in saved] == ["candidate"] * 2 + [
        "ongoing"
    ] * 4 + ["recovery_wait"] * 2 + ["recovered"]
    latest = reader.incident(first)
    assert latest.recovered_at == samples[8].timestamp
    assert latest.last_detected_at == samples[5].timestamp
    assert latest.evidence == changes[5][0].evidence
    assert saved[-1]["record"]["motor_housing_temp_c"] == 65
    assert [e["kind"] for e in reader.events(first)] == [
        "confirmed",
        "updated",
        "escalated",
        "updated",
        "recovered",
    ]
    second = reader.incident(changes[11][0].incident_id)
    assert second.status == IncidentStatus.OPEN
    assert reader.metadata(second.incident_id)["collection_end_reason"] == "input_end"


@pytest.mark.parametrize(
    "severity,phase",
    [(Severity.UNKNOWN, "unknown"), (Severity.SUPPRESSED, "suppressed")],
)
def test_unknown_suppressed_and_gap_interrupt_recovery(tmp_path, severity, phase):
    with collector(tmp_path) as detector:
        for i in range(3):
            changed = detector.process(row(i), assessments=items(Severity.WARNING))
        incident_id = changed[0].incident_id
        detector.process(row(3), assessments=items(Severity.NORMAL))
        detector.process(row(4), assessments=items(severity))
        detector.process(row(8), assessments=items(Severity.NORMAL))
        detector.process(row(9), assessments=items(Severity.NORMAL))
        assert detector.active_incidents()[0].status == IncidentStatus.OPEN
    reader = HistoryReader(detector.run_path)
    saved = list(reader.telemetry(incident_id))
    assert saved[4]["annotation"]["collection_phase"] == phase
    assert saved[5]["annotation"]["gap_seconds"] == 4
    assert saved[5]["annotation"]["normal_since"] == row(8).timestamp.isoformat()
    assert reader.metadata(incident_id)["gap_count"] == 1
    assert reader.incident(incident_id).status == IncidentStatus.OPEN
    assert reader.validate()


def test_duplicate_and_no_history_behavior_change(tmp_path):
    normal = RuleDetector(enabled_codes={CODE}, policies={CODE: RulePolicy(2, 1, 2)})
    with collector(tmp_path) as detector:
        for i in range(8):
            severity = Severity.WARNING if i < 5 else Severity.NORMAL
            base = normal.process_assessments(row(i), items(severity))
            saved = detector.process(row(i), assessments=items(severity))
            assert [v.model_dump(exclude={"incident_id"}) for v in saved] == [
                v.model_dump(exclude={"incident_id"}) for v in base
            ]
            assert detector.process(row(i), assessments=items(severity)) == []
    reader = HistoryReader(detector.run_path)
    incident_id = reader.list_incidents()[0]
    assert len(list(reader.telemetry(incident_id))) == 8
    assert len(list(reader.events(incident_id))) == 4
    assert reader.validate()


@pytest.mark.parametrize("bad", [row(0, rpm=1), row(-1), row(1, record_id="row-0")])
def test_time_reversal_or_id_conflict_poison_run(tmp_path, bad):
    detector = collector(tmp_path)
    detector.process(row(0), assessments=items(Severity.WARNING))
    with pytest.raises(ValueError):
        detector.process(bad, assessments=items(Severity.WARNING))
    with pytest.raises(HistoryError):
        detector.process(row(3), assessments=items(Severity.WARNING))
    with pytest.raises(HistoryError):
        HistoryReader(detector.run_path).validate()


def test_non_adjacent_reused_id_is_not_silently_overwritten(tmp_path):
    detector = collector(tmp_path)
    for i in range(3):
        detector.process(row(i), assessments=items(Severity.WARNING))
    with pytest.raises(ValueError):
        detector.process(row(3, record_id="row-0"), assessments=items(Severity.WARNING))


@pytest.mark.parametrize(
    "config", [HistoryConfig(buffer_seconds=1), HistoryConfig(buffer_rows=2)]
)
def test_buffer_truncation_is_explicit(tmp_path, config):
    with collector(tmp_path, config=config) as detector:
        for i in range(3):
            changed = detector.process(row(i), assessments=items(Severity.WARNING))
    reader = HistoryReader(detector.run_path)
    meta = reader.metadata(changed[0].incident_id)
    assert meta["candidate_prefix_missing"] is True
    assert meta["actual_start"] == row(1).timestamp.isoformat()
    assert meta["requested_start"] == row(0).timestamp.isoformat()
    assert reader.validate()


def test_simultaneous_incidents_and_assets_are_separate(tmp_path):
    with HistoryDetector(tmp_path, enabled_codes={CODE, OTHER}) as detector:
        for i in range(12):
            for process, asset in (("p1", "a"), ("p1", "b"), ("p2", "a")):
                detector.process(
                    row(i, process_id=process, asset_id=asset),
                    assessments=items(Severity.ERROR, (CODE, OTHER)),
                )
    reader = HistoryReader(detector.run_path)
    assert len(reader.list_incidents()) == 6
    for incident_id in reader.list_incidents():
        incident = reader.incident(incident_id)
        samples = list(reader.telemetry(incident_id))
        assert all(
            (e["record"]["process_id"], e["record"]["asset_id"])
            == (incident.process_id, incident.asset_id)
            for e in samples
        )
        assert len(samples) == 12
    assert reader.validate()


def test_unique_runs_and_abrupt_or_exception_exit(tmp_path):
    first, second = collector(tmp_path), collector(tmp_path)
    assert first.run_path != second.run_path
    with pytest.raises(HistoryError, match="incomplete"):
        HistoryReader(first.run_path).validate()
    first.close()
    assert HistoryReader(first.run_path).validate()
    with pytest.raises(RuntimeError):
        with second:
            raise RuntimeError("input failure")
    assert HistoryReader(second.run_path).manifest["status"] == "failed"


def test_append_failure_is_not_retryable_and_pending_is_visible(tmp_path, monkeypatch):
    detector = collector(tmp_path)
    for i in range(2):
        detector.process(row(i), assessments=items(Severity.WARNING))
    original = Path.open

    def fail(path, *args, **kwargs):
        if path.name == "events.jsonl" and args and args[0] == "ab":
            raise OSError("simulated full disk")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError, match="full disk"):
        detector.process(row(2), assessments=items(Severity.WARNING))
    with pytest.raises(HistoryError):
        detector.process(row(2), assessments=items(Severity.WARNING))
    reader = HistoryReader(detector.run_path)
    assert reader.manifest["pending_input"]["record_id"] == "row-2"
    with pytest.raises(HistoryError):
        reader.validate()


@pytest.mark.parametrize("damage", [b'{"truncated":', b'{"invalid":true}\n'])
def test_corrupt_or_extra_jsonl_is_never_ignored(tmp_path, damage):
    with collector(tmp_path) as detector:
        for i in range(3):
            changes = detector.process(row(i), assessments=items(Severity.WARNING))
    reader = HistoryReader(detector.run_path)
    incident_id = changes[0].incident_id
    with (detector.run_path / incident_id / "telemetry.jsonl").open("ab") as file:
        file.write(damage)
    with pytest.raises(HistoryError):
        reader.validate()


def test_valid_json_tamper_and_atomic_snapshot_detected(tmp_path):
    with collector(tmp_path) as detector:
        for i in range(3):
            changes = detector.process(row(i), assessments=items(Severity.WARNING))
    reader = HistoryReader(detector.run_path)
    incident_id = changes[0].incident_id
    path = detector.run_path / incident_id / "incident.json"
    path.write_text(
        path.read_text(encoding="utf-8").replace('"OPEN"', '"CLOSED"'), encoding="utf-8"
    )
    with pytest.raises(HistoryError, match="checkpoint"):
        reader.validate()


def test_memory_limits_fail_explicitly(tmp_path):
    detector = collector(tmp_path, config=HistoryConfig(max_records=1))
    detector.process(row(0), assessments=items(Severity.NORMAL))
    with pytest.raises(HistoryError, match="record limit"):
        detector.process(row(1), assessments=items(Severity.NORMAL))


def test_csv_round_trip_and_v4_m10(tmp_path):
    csv_path = ROOT / "data/telemetry/battery_tray_transfer_5min_warning_error_v4.csv"
    if not csv_path.exists():
        pytest.skip("Real v4 CSV is unavailable; synthetic lifecycle tested separately")
    originals = {}
    with HistoryDetector(tmp_path, source={"context_preset": "MINIMAL"}) as detector:
        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            for i, raw in enumerate(csv.DictReader(file)):
                record = TelemetryRecord.model_validate(raw)
                originals[record.record_id] = record
                detector.process(
                    record,
                    {
                        "run_cmd": True,
                        "events_reliable": True,
                        "downstream_ready": True,
                        "tracking_reset": i == 0
                        and not record.infeed_present
                        and not record.outfeed_present,
                    },
                )
    reader = HistoryReader(detector.run_path)
    assert reader.validate()
    for incident_id in reader.list_incidents():
        for entry in reader.telemetry(incident_id):
            assert entry["record"] == originals[
                entry["record"]["record_id"]
            ].model_dump(mode="json")
    m10 = [i for i in reader.list_incidents() if CODE in reader.incident(i).codes]
    assert len(m10) == 1
    incident_id = m10[0]
    incident = reader.incident(incident_id)
    origin = min(r.timestamp for r in originals.values())

    def seconds(at):
        return int((at - origin).total_seconds())

    assert [
        seconds(at)
        for at in (
            incident.first_detected_at,
            incident.confirmed_at,
            incident.last_detected_at,
            incident.recovered_at,
        )
    ] == [81, 91, 136, 147]
    events = list(reader.events(incident_id))
    assert [
        seconds(datetime.fromisoformat(e["timestamp"]))
        for e in events
        if e["kind"] == "escalated"
    ] == [109]
    telemetry = list(reader.telemetry(incident_id))
    assert len(telemetry) == 67
    assert [
        seconds(datetime.fromisoformat(e["record"]["timestamp"])) for e in telemetry
    ] == list(range(81, 148))
    wait = [
        e for e in telemetry if e["annotation"]["collection_phase"] == "recovery_wait"
    ]
    assert [
        seconds(datetime.fromisoformat(e["record"]["timestamp"])) for e in wait
    ] == list(range(137, 147))


def test_unknown_schema_and_reader_path_validation(tmp_path):
    with collector(tmp_path) as detector:
        pass
    reader = HistoryReader(detector.run_path)
    with pytest.raises(HistoryError):
        reader.incident("../../oops")
    manifest = detector.run_path / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["schema_version"] = "future"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(HistoryError, match="schema_version"):
        HistoryReader(detector.run_path)


def test_two_second_sampling_gap_is_visible_without_detector_interrupt(tmp_path):
    with collector(tmp_path) as detector:
        for second in (0, 1, 2, 4):
            changed = detector.process(row(second), assessments=items(Severity.WARNING))
    reader = HistoryReader(detector.run_path)
    incident_id = changed[0].incident_id
    last = list(reader.telemetry(incident_id))[-1]["annotation"]
    assert last["input_delta_seconds"] == 2
    assert last["gap_seconds"] is None
    assert reader.metadata(incident_id)["sampling_discontinuity_count"] == 1
    assert reader.validate()


def test_past_event_start_beyond_buffer_and_config_snapshot(tmp_path):
    with HistoryDetector(tmp_path, enabled_codes={"BTT2-P01"}) as detector:
        for second in range(4):
            changed = detector.process(
                row(second),
                assessments=[
                    RuleAssessment(
                        "BTT2-P01",
                        Severity.ERROR,
                        started_at=T0 - timedelta(seconds=300),
                    )
                ],
            )
    reader = HistoryReader(detector.run_path)
    meta = reader.metadata(changed[0].incident_id)
    assert meta["candidate_prefix_missing"] is True
    assert meta["actual_start"] == T0.isoformat()
    settings = reader.manifest["detector"]
    assert settings["policies"][CODE]["warning_s"] == 10
    assert settings["numeric_rules"]
    assert len(settings["implementation_sha256"]["rule_engine.py"]) == 64
    assert reader.validate()


def test_nonfinite_input_and_context_are_preserved_as_unknown(tmp_path):
    with HistoryDetector(tmp_path, enabled_codes={CODE}) as detector:
        for second in range(11):
            changed = detector.process(
                row(second, motor_housing_temp_c=90), {"run_cmd": True}
            )
        incident_id = changed[0].incident_id
        detector.process(row(11, rpm=float("nan")), {"telemetry_valid": False})
    reader = HistoryReader(detector.run_path)
    last = list(reader.telemetry(incident_id))[-1]
    assert str(last["record"]["rpm"]) == "nan"
    assert last["annotation"]["collection_phase"] == "unknown"
    assert last["annotation"]["plc_context"] == {"telemetry_valid": False}
    assert reader.validate()


def test_atomic_replace_failure_stops_and_marks_incomplete(tmp_path, monkeypatch):
    import weeing_weeing.detector.history as history

    detector = collector(tmp_path)
    for second in range(2):
        detector.process(row(second), assessments=items(Severity.WARNING))
    original = history.os.replace

    def fail(source, destination):
        if Path(destination).name == "incident.json":
            raise OSError("replace failed")
        return original(source, destination)

    monkeypatch.setattr(history.os, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        detector.process(row(2), assessments=items(Severity.WARNING))
    reader = HistoryReader(detector.run_path)
    assert reader.manifest["completed"] is False
    assert list(detector.run_path.rglob("incident.json.tmp"))
    with pytest.raises(HistoryError):
        reader.validate()
    with pytest.raises(HistoryError):
        detector.close()


def test_event_time_uses_input_row_and_original_incident_contract(tmp_path):
    from weeing_weeing.contracts import Incident

    with collector(tmp_path) as detector:
        for second in range(6):
            changed = detector.process(
                row(second),
                assessments=items(Severity.WARNING if second < 3 else Severity.NORMAL),
            )
    reader = HistoryReader(detector.run_path)
    incident_id = changed[0].incident_id
    events = list(reader.events(incident_id))
    assert [(e["timestamp"], e["record_id"]) for e in events] == [
        (row(2).timestamp.isoformat(), "row-2"),
        (row(5).timestamp.isoformat(), "row-5"),
    ]
    latest = Incident.model_validate_json(
        (detector.run_path / incident_id / "incident.json").read_text(encoding="utf-8")
    )
    assert latest == reader.incident(incident_id)
    assert reader.validate()


def test_asset_limit_is_explicit_and_normal_buffer_has_row_bound(tmp_path):
    detector = collector(tmp_path, config=HistoryConfig(buffer_rows=2, max_assets=1))
    for second in range(5):
        detector.process(row(second), assessments=items(Severity.NORMAL))
    assert len(detector._buffers[("process", "asset")]) == 2
    assert HistoryReader(detector.run_path).list_incidents() == []
    with pytest.raises(HistoryError, match="asset limit"):
        detector.process(row(5, asset_id="other"), assessments=items(Severity.NORMAL))


def test_context_key_order_does_not_create_false_conflicting_duplicate(tmp_path):
    with collector(tmp_path) as detector:
        detector.process(row(0), {"a": 1, "b": 2}, assessments=items(Severity.WARNING))
        assert (
            detector.process(
                row(0), {"b": 2, "a": 1}, assessments=items(Severity.WARNING)
            )
            == []
        )
    assert HistoryReader(detector.run_path).validate()
