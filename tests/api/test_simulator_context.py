import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from weeing_weeing.api.app import app
from weeing_weeing.api.simulator_context import ENABLED, parse_simulator_frame
from weeing_weeing.contracts import IncidentStatus, Severity, TelemetryRecord
from weeing_weeing.detector.interface import RuleDetector
from weeing_weeing.ingest.interface import TelemetryInputError, parse_telemetry_json

T0 = datetime(2026, 11, 4, tzinfo=UTC)


def context(**updates):
    return {
        "version": "unreal-state-v1",
        "source_id": "source-1",
        "run_cmd": True,
        "run_started_at": T0.isoformat(),
        "run_started_simulation_seconds": 0,
        "simulation_seconds": 0,
        "last_infeed_simulation_seconds": None,
        "last_outfeed_simulation_seconds": None,
        "fixed_speed": True,
        "same_load": True,
        "vibration_comparable": True,
        "downstream_ready": True,
        "recipe_id": "synthetic-1",
        "config_version": "1",
        "origin_verified_empty": True,
        "events_complete": True,
        "sequence": 0,
        "last_infeed_at": None,
        "last_outfeed_at": None,
        "pending": [],
        "events": [],
        **updates,
    }


def frame(sample_rows, second=0, ctx=None, simulation_second=None, **sensors):
    row = TelemetryRecord.model_validate(sample_rows[0]).model_dump(mode="json")
    row.update(
        record_id=f"sample-{second}",
        timestamp=(T0 + timedelta(seconds=second)).isoformat(),
        rpm=1015,
        dc_input_current_a=0.092,
        dc_bus_voltage_v=24,
        motor_housing_temp_c=66,
        de_vibration_rms_g=0.06,
        de_kurtosis=5,
        nde_vibration_rms_g=0.055,
        nde_kurtosis=4,
        infeed_present=False,
        outfeed_present=False,
    )
    row.update(sensors)
    source = deepcopy(context() if ctx is None else ctx)
    source["simulation_seconds"] = (
        second if simulation_second is None else simulation_second
    )

    def clock(at):
        return (datetime.fromisoformat(at) - T0).total_seconds()

    for name in ("infeed", "outfeed"):
        if (
            source[f"last_{name}_at"] is not None
            and source[f"last_{name}_simulation_seconds"] is None
        ):
            source[f"last_{name}_simulation_seconds"] = clock(source[f"last_{name}_at"])
    for item in source["pending"]:
        item.setdefault("simulation_seconds", clock(item["entered_at"]))
    for event in source["events"]:
        event.setdefault("simulation_seconds", clock(event["at"]))
    return {
        "message_type": "telemetry_with_context_v1",
        "telemetry": row,
        "context": source,
    }


def evaluate(detector, data):
    wire, ctx = parse_simulator_frame(json.dumps(data))
    return detector.process(parse_telemetry_json(wire), ctx)


def test_startup_and_warmup_do_not_generate_missing_context(sample_rows):
    for _ in range(2):  # Independent launches create no D04/D05 incident.
        detector = RuleDetector(enabled_codes=ENABLED)
        changes = [
            item
            for s in range(0, 40)
            for item in evaluate(detector, frame(sample_rows, s))
        ]
        assert changes == []
        by_code = {item.rule_code: item for item in detector.last_assessments}
        assert by_code["BTT2-M09"].severity == Severity.UNKNOWN
        assert not by_code["BTT2-M09"].context_missing
        assert "BTT2-M04" not in by_code and "BTT2-M19" not in by_code


def test_real_pulses_between_samples_and_sequence_gap(sample_rows):
    detector = RuleDetector(enabled_codes=ENABLED)
    evaluate(detector, frame(sample_rows))
    at = (T0 + timedelta(seconds=0.1)).isoformat()
    tray = dict(item_id="tray-a", entered_at=at, sequence=1)
    first = context(
        sequence=1,
        pending=[tray],
        events=[dict(item_id="tray-a", at=at, sequence=1, kind="infeed")],
        last_infeed_at=at,
    )
    assert evaluate(detector, frame(sample_rows, 0.5, first)) == []
    out = (T0 + timedelta(seconds=12.1)).isoformat()
    # Keep source checkpoints without inventing occupancy pulses.
    for index in range(1, 25):
        evaluate(detector, frame(sample_rows, index / 2, {**first, "events": []}))
    changes = evaluate(
        detector,
        frame(
            sample_rows,
            12.5,
            {
                **first,
                "sequence": 2,
                "pending": [],
                "last_outfeed_at": out,
                "events": [dict(item_id="tray-a", at=out, sequence=2, kind="outfeed")],
            },
        ),
    )
    assert not any("BTT2-D04" in i.codes for i in changes)
    changes = evaluate(detector, frame(sample_rows, 13, context(sequence=4)))
    assert any("BTT2-D04" in i.codes for i in changes)


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"origin_verified_empty": False}, "BTT2-D04"),
        ({"events_complete": False}, "BTT2-D04"),
        ({"same_load": None}, "BTT2-D05"),
    ],
)
def test_missing_evidence_is_still_a_quality_warning(sample_rows, updates, code):
    detector = RuleDetector(enabled_codes=ENABLED)
    changes = evaluate(detector, frame(sample_rows, 5, context(**updates)))
    assert any(code in i.codes for i in changes)


def test_m03_escalation_and_recovery_with_source_context(sample_rows):
    detector = RuleDetector(enabled_codes=ENABLED)
    changes = []
    for s in range(30):
        changes += evaluate(
            detector,
            frame(sample_rows, s, rpm=1035 if s < 9 else 1045 if s < 16 else 1015),
        )
    events = [i for i in changes if "BTT2-M03" in i.codes]
    assert events[0].severity == Severity.WARNING
    assert any(i.severity == Severity.ERROR for i in events)
    assert len({i.incident_id for i in events}) == 1
    assert events[-1].status == IncidentStatus.RECOVERED
    assert not any(set(i.codes) & {"BTT2-D04", "BTT2-D05"} for i in changes)


def test_envelope_strict_and_raw_contract_unchanged(sample_rows):
    data = frame(sample_rows)
    wire, _ = parse_simulator_frame(json.dumps(data))
    assert len(json.loads(wire)) == 15
    with pytest.raises(TelemetryInputError):
        parse_telemetry_json(json.dumps(data))
    for invalid in [
        [],
        {**data, "extra": True},
        {
            **data,
            "context": context(run_started_at=(T0 + timedelta(seconds=1)).isoformat()),
        },
    ]:
        with pytest.raises(TelemetryInputError):
            parse_simulator_frame(json.dumps(invalid))
    with pytest.raises(TelemetryInputError):
        parse_simulator_frame(
            json.dumps(data).replace('"sequence": 0', '"sequence": 0, "sequence": 0')
        )


def test_p03_signal_fault_is_independent_of_actor_tracking(sample_rows):
    detector = RuleDetector(enabled_codes=ENABLED)
    changes = []
    for index in range(24):
        changes += evaluate(
            detector, frame(sample_rows, index / 2, infeed_present=index < 17)
        )
    p03 = [i for i in changes if "BTT2-P03" in i.codes]
    assert any(i.severity == Severity.ERROR for i in p03)
    assert p03[-1].status == IncidentStatus.RECOVERED
    assert not any(set(i.codes) & {"BTT2-D04", "BTT2-D05"} for i in changes)


def test_verified_nonempty_checkpoint_after_new_connection(sample_rows):
    at = T0.isoformat()
    checkpoint = context(
        sequence=1,
        last_infeed_at=at,
        pending=[dict(item_id="a", entered_at=at, sequence=1)],
    )
    detector = RuleDetector(enabled_codes=ENABLED)
    assert evaluate(detector, frame(sample_rows, 1, checkpoint)) == []
    changed = evaluate(detector, frame(sample_rows, 1.5, {**checkpoint, "pending": []}))
    assert any("BTT2-D04" in i.codes for i in changed)


def test_old_raw_run_only_keeps_missing_context_warning(sample_rows):
    record = TelemetryRecord.model_validate(frame(sample_rows)["telemetry"])
    changes = RuleDetector().process(record, {"run_cmd": True})
    assert any("BTT2-D04" in i.codes for i in changes)
    assert any("BTT2-D05" in i.codes for i in changes)


def test_pause_wall_time_does_not_become_run_or_transit_time(sample_rows):
    at = (T0 + timedelta(seconds=1)).isoformat()
    checkpoint = context(
        sequence=1,
        last_infeed_at=at,
        last_infeed_simulation_seconds=1,
        pending=[dict(item_id="a", entered_at=at, sequence=1, simulation_seconds=1)],
    )
    # Reconnect after 900 wall seconds, only 5 simulated seconds have elapsed.
    detector = RuleDetector(enabled_codes=ENABLED)
    assert (
        evaluate(
            detector,
            frame(
                sample_rows,
                900,
                checkpoint,
                simulation_second=5,
                motor_housing_temp_c=35,
            ),
        )
        == []
    )
    by_code = {a.rule_code: a for a in detector.last_assessments}
    assert by_code["BTT2-M09"].severity == Severity.UNKNOWN
    assert by_code["BTT2-D04"].severity == Severity.NORMAL
    assert by_code["BTT2-D05"].severity == Severity.NORMAL
    # Real UTC remains 900 seconds; a normal 14-second simulated transit follows.
    evaluate(detector, frame(sample_rows, 900.5, checkpoint, simulation_second=5.5))
    out = (T0 + timedelta(seconds=901)).isoformat()
    done = {
        **checkpoint,
        "sequence": 2,
        "pending": [],
        "last_outfeed_at": out,
        "last_outfeed_simulation_seconds": 15,
        "events": [
            dict(item_id="a", at=out, sequence=2, kind="outfeed", simulation_seconds=15)
        ],
    }
    changes = evaluate(detector, frame(sample_rows, 901, done, simulation_second=15))
    assert not any(
        set(i.codes) & {"BTT2-P01", "BTT2-P02", "BTT2-P06", "BTT2-D04", "BTT2-D05"}
        for i in changes
    )
    # No new feed for 14 active seconds genuinely warrants P05.
    assert any("BTT2-P05" in i.codes for i in changes)


def test_active_simulation_timeout_still_reports_actual_utc_origin(sample_rows):
    at = (T0 + timedelta(seconds=100)).isoformat()
    checkpoint = context(
        sequence=1,
        last_infeed_at=at,
        last_infeed_simulation_seconds=1,
        pending=[dict(item_id="a", entered_at=at, sequence=1, simulation_seconds=1)],
    )
    changes = evaluate(
        RuleDetector(enabled_codes=ENABLED),
        frame(sample_rows, 200, checkpoint, simulation_second=18),
    )
    faults = [i for i in changes if set(i.codes) & {"BTT2-P01", "BTT2-P05", "BTT2-P06"}]
    assert len(faults) == 3
    assert all(i.first_detected_at == T0 + timedelta(seconds=100) for i in faults)


def test_run_off_duration_is_excluded_from_pending_tray_time(sample_rows):
    at = T0.isoformat()
    checkpoint = context(
        sequence=1,
        last_infeed_at=at,
        last_infeed_simulation_seconds=0,
        pending=[dict(item_id="a", entered_at=at, sequence=1, simulation_seconds=0)],
    )
    detector = RuleDetector(enabled_codes=ENABLED)
    evaluate(detector, frame(sample_rows, 0, checkpoint, simulation_second=0))
    stopped = {
        **checkpoint,
        "run_cmd": False,
        "run_started_at": None,
        "run_started_simulation_seconds": None,
    }
    evaluate(detector, frame(sample_rows, 0.5, stopped, simulation_second=0.5))
    resumed = {
        **checkpoint,
        "run_started_at": (T0 + timedelta(seconds=25)).isoformat(),
        "run_started_simulation_seconds": 0.5,
    }
    changed = evaluate(detector, frame(sample_rows, 25, resumed, simulation_second=0.5))
    assert not any(
        set(i.codes) & {"BTT2-P01", "BTT2-P05", "BTT2-P06", "BTT2-D04", "BTT2-D05"}
        for i in changed
    )


def test_inconsistent_checkpoint_cannot_publish_transfer_decision(sample_rows):
    detector = RuleDetector(enabled_codes=ENABLED)
    entered = T0.isoformat()
    checkpoint = context(
        sequence=1,
        last_infeed_at=entered,
        pending=[dict(item_id="a", entered_at=entered, sequence=1)],
    )
    evaluate(detector, frame(sample_rows, 0, checkpoint))
    out = (T0 + timedelta(seconds=8)).isoformat()
    broken = {
        **checkpoint,
        "sequence": 2,
        "last_outfeed_at": out,
        "events": [dict(item_id="a", at=out, sequence=2, kind="outfeed")],
    }
    evaluate(detector, frame(sample_rows, 0.5, checkpoint))
    # No gap reset: deliver a fast, invalid transfer plus contradictory inventory.
    broken["events"][0]["at"] = (T0 + timedelta(seconds=1)).isoformat()
    broken["last_outfeed_at"] = broken["events"][0]["at"]
    changes = evaluate(detector, frame(sample_rows, 1, broken))
    assert any("BTT2-D04" in i.codes for i in changes)
    assessments = {item.rule_code: item for item in detector.last_assessments}
    assert assessments["BTT2-P02"].severity == Severity.UNKNOWN


def test_websocket_opt_in_and_coverage(sample_rows, tmp_path, monkeypatch):
    monkeypatch.setenv("TELEMETRY_HISTORY_DIR", str(tmp_path))
    monkeypatch.setenv("TELEMETRY_DB_ENABLED", "false")
    monkeypatch.setenv("ANALYSIS_AUTO_ENABLED", "false")
    monkeypatch.setenv("TELEMETRY_UNREAL_CONTEXT_ENABLED", "false")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry?context=UNREAL_STATE") as ws:
            assert ws.receive_json()["code"] == "unreal_context_disabled"
    monkeypatch.setenv("TELEMETRY_UNREAL_CONTEXT_ENABLED", "true")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry?context=UNREAL_STATE") as ws:
            assert ws.receive_json()["status"] == "connected"
            ws.send_json(frame(sample_rows))
            ack = ws.receive_json()
            assert ack["status"] == "processed"
            assert ack["incidents"] == []
            assert set(ack["rule_coverage"]["excluded"]) == {"BTT2-M04", "BTT2-M19"}


def test_new_profile_does_not_duplicate_or_recover_old_db_warnings(
    sample_rows, tmp_path, monkeypatch
):
    from weeing_weeing.db.interface import get_incidents

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'isolated.db'}")
    monkeypatch.setenv("TELEMETRY_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setenv("TELEMETRY_DB_ENABLED", "true")
    monkeypatch.setenv("ANALYSIS_AUTO_ENABLED", "false")
    monkeypatch.setenv("TELEMETRY_UNREAL_CONTEXT_ENABLED", "true")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry?context=RUN_ONLY") as ws:
            ws.receive_json()
            ws.send_json(frame(sample_rows)["telemetry"])
            assert ws.receive_json()["db_status"] == "saved"
        old = get_incidents().list_incidents()
        assert {code for i in old for code in i.codes} == {"BTT2-D04", "BTT2-D05"}
        before = {i.incident_id: i.model_dump(mode="json") for i in old}
        for second in (1, 2):
            with client.websocket_connect("/ws/telemetry?context=UNREAL_STATE") as ws:
                ws.receive_json()
                ws.send_json(frame(sample_rows, second))
                ack = ws.receive_json()
                assert ack["db_status"] == "saved"
                assert ack["analysis_jobs"] == []
                assert ack["incidents"] == []
        assert {
            i.incident_id: i.model_dump(mode="json")
            for i in get_incidents().list_incidents()
        } == before
