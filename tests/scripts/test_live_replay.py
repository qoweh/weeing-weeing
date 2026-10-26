"""The console observer must preserve actual replay/history results."""

import csv
import json
import runpy
import sys
from datetime import datetime, timedelta
from pathlib import Path

from weeing_weeing.contracts import TelemetryRecord
from weeing_weeing.detector.interface import RuleDetector

ROOT = Path(__file__).resolve().parents[2]


def test_live_and_quiet_cli_have_same_history_results(
    tmp_path, sample_rows, monkeypatch, capsys
):
    path = tmp_path / "lifecycle.csv"
    base = sample_rows[0]
    origin = datetime.fromisoformat(base["timestamp"])
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(base))
        writer.writeheader()
        for second in range(36):
            writer.writerow(
                {
                    **base,
                    "record_id": f"live-{second}",
                    "timestamp": (origin + timedelta(seconds=second)).isoformat(),
                    "motor_housing_temp_c": (
                        88 if second < 12 else 120 if second < 24 else 65
                    ),
                    "dc_input_current_a": "",
                }
            )

    summaries = []
    for live in (False, True):
        argv = [
            str(ROOT / "scripts/demo_incident_history.py"),
            "--csv",
            str(path),
            "--output",
            str(tmp_path / "history"),
            "--codes",
            "BTT2-M10",
            "--interval",
            "0",
        ]
        if live:
            argv.append("--live")
        monkeypatch.setattr(sys, "argv", argv)
        runpy.run_path(argv[0], run_name="__main__")
        captured = capsys.readouterr()
        summary = json.loads(captured.out)
        assert summary["input_rows"] == 36
        assert len(summary["incidents"]) == 1
        assert summary["incidents"][0]["status"] == "RECOVERED"
        summaries.append(summary["incidents"][0])
        if live:
            assert captured.err.count("[수신 #") == 36
            assert "sensor_time=" + origin.isoformat() in captured.err
            assert "PC=" in captured.err and "elapsed=" in captured.err
            assert "dc_input_current_a=null" in captured.err
            assert "[신규 사건] BTT2-M10" in captured.err
            assert "[등급 변경] BTT2-M10 severity=Error" in captured.err
            assert "[회복] BTT2-M10" in captured.err
            assert "[완료] 36행 처리, HistoryReader 무결성 검증 통과" in captured.err
        else:
            assert captured.err == ""
    assert {k: v for k, v in summaries[0].items() if k != "incident_id"} == {
        k: v for k, v in summaries[1].items() if k != "incident_id"
    }


def test_d05_console_reports_only_changed_requirements_recovery_and_recurrence(
    sample_rows, capsys
):
    namespace = runpy.run_path(str(ROOT / "scripts/demo_incident_history.py"))
    observer = namespace["LiveReplay"]()
    detector = RuleDetector(enabled_codes={"BTT2-D05"})
    started = datetime.fromisoformat(sample_rows[0]["timestamp"]) - timedelta(
        seconds=700
    )
    minimal = {"run_cmd": True}
    partial = {**minimal, "run_started_at": started, "fixed_speed": True}
    complete = {
        **partial,
        "same_load": True,
        "vibration_comparable": True,
        "vibration_baseline": {
            "de": 0.06,
            "nde": 0.055,
            "approved": True,
            "version": "test",
        },
    }
    for index, raw in enumerate(sample_rows[:15]):
        context = (
            minimal if index < 2 or index == 14 else partial if index == 2 else complete
        )
        observer.processed(
            detector.process(
                TelemetryRecord.model_validate(
                    {
                        **raw,
                        "dc_input_current_a": 0.091,
                        "motor_housing_temp_c": 65,
                    }
                ),
                context,
            )
        )
    output = capsys.readouterr().err
    assert output.count("[D05 문맥 부족]") == 3
    assert output.count("[D05 해소]") == 1
    first, changed, recurrence = output.split("[D05 문맥 부족]")[1:]
    assert "RPM:" in first and "전류:" in first
    assert "저온:" in first and "진동:" in first and "상대 진동:" in first
    assert "RPM:" not in changed and "전류:" in changed
    assert "RPM:" in recurrence
    assert "candidate=" not in output  # timestamps do not trigger repeated D05 logs


def test_d05_repeat_suppression_preserves_all_history_events(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(ROOT / "scripts/demo_incident_history.py"),
            "--output",
            str(tmp_path),
            "--codes",
            "BTT2-D05",
            "--interval",
            "0",
            "--live",
        ],
    )
    runpy.run_path(sys.argv[0], run_name="__main__")
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["input_rows"] == 60
    assert summary["incidents"][0]["events"] == 60
    assert captured.err.count("[수신 #") == 60
    assert captured.err.count("[D05 문맥 부족]") == 1
