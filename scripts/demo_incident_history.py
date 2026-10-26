"""CSV -> opt-in file history; input/output CLI paths, streaming readback and sizes.

Run: uv run --no-sync python scripts/demo_incident_history.py --help
Default input: data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv
Default output: outputs/incident_history/<unique run>/
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weeing_weeing.contracts import Incident, IncidentStatus, TelemetryRecord  # noqa: E402
from weeing_weeing.detector.interface import (  # noqa: E402
    HistoryConfig,
    HistoryDetector,
    HistoryReader,
)
from weeing_weeing.ingest.interface import (  # noqa: E402
    CsvJsonSource,
    JsonTelemetryInput,
    replay_json,
)


class LiveReplay:
    """Terminal-only observer; receives validated rows and actual detector changes."""

    def __init__(self):
        self.started = time.monotonic()
        self.rows = 0
        self.severities = {}
        self.d05_states = {}

    def write(self, text):
        # Keep stdout as the existing machine-readable final JSON summary.
        print(text, file=sys.stderr, flush=True)

    def received(self, record: TelemetryRecord):
        self.rows += 1
        elapsed = time.monotonic() - self.started
        pc_time = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.write(
            f"[수신 #{self.rows:04d}] PC={pc_time} elapsed={elapsed:.2f}s "
            f"sensor_time={record.timestamp.isoformat()} id={record.record_id}"
        )
        fields = record.model_dump()
        sensors = " ".join(
            f"{name}={json.dumps(value, ensure_ascii=False)}"
            for name, value in fields.items()
            if name
            not in (
                "record_id",
                "timestamp",
                "process_id",
                "asset_id",
                "schema_version",
            )
        )
        self.write(f"  [센서] {sensors}")

    def processed(self, changes: list[Incident]):
        if not changes:
            self.write("  [처리 완료] 사건 변화 없음 (정상 판정을 뜻하지 않음)")
        for incident in changes:
            if incident.codes == ["BTT2-D05"]:
                self.show_d05(incident)
                continue
            previous = self.severities.get(incident.incident_id)
            if incident.status == IncidentStatus.RECOVERED:
                label = "회복"
            elif previous is None:
                label = "신규 사건"
            elif previous != incident.severity:
                label = "등급 변경"
            else:
                label = "사건 갱신"
            self.severities[incident.incident_id] = incident.severity
            self.write(
                f"  [{label}] {','.join(incident.codes)} "
                f"severity={incident.severity.value} status={incident.status.value} "
                f"id={incident.incident_id}"
            )
            self.write(
                f"    candidate={incident.first_detected_at.isoformat()} "
                f"confirmed={incident.confirmed_at.isoformat() if incident.confirmed_at else '-'} "
                f"last_abnormal={incident.last_detected_at.isoformat()} "
                f"recovered={incident.recovered_at.isoformat() if incident.recovered_at else '-'}"
            )

    def show_d05(self, incident: Incident):
        # D05 evidence contains the evaluator's missing-context codes. Only
        # presentation is grouped here; no context is inferred or supplied.
        reasons = tuple(
            sorted(
                {
                    evidence.observed
                    for evidence in incident.evidence
                    if evidence.observed
                }
            )
        )
        state = (incident.status, incident.severity, reasons, incident.reason)
        key = (incident.process_id, incident.asset_id, incident.incident_id)
        if self.d05_states.get(key) == state:
            return
        self.d05_states[key] = state
        if incident.status == IncidentStatus.RECOVERED:
            self.write(f"  [D05 해소] BTT2-D05 | id={incident.incident_id}")
            return
        codes = set(re.findall(r"BTT2-[A-Z]\d{2}", " ".join(reasons)))
        self.write(
            f"  [D05 문맥 부족] BTT2-D05 | asset={incident.asset_id} "
            f"severity={incident.severity.value} status={incident.status.value} "
            f"id={incident.incident_id}"
        )
        groups = (
            ({"BTT2-M02", "BTT2-M03"}, "RPM: 운전·기동 경과·고정 속도 조건 확인 필요"),
            (
                {"BTT2-M05", "BTT2-M06"},
                "전류: 운전·기동 경과·동일 속도/하중 조건 확인 필요",
            ),
            ({"BTT2-M09"}, "저온: 운전·예열 600초 조건 확인 필요"),
            (
                {f"BTT2-M{n}" for n in range(11, 19)},
                "진동: 동일 속도·하중·측정 조건 확인 필요",
            ),
            ({"BTT2-M19"}, "상대 진동: 승인된 정상 기준값·비교 조건 확인 필요"),
        )
        for group, description in groups:
            affected = codes & group
            if affected:
                self.write(f"    - {description} ({', '.join(sorted(affected))})")
                codes -= affected
        if codes:
            self.write(f"    - 추가 판정 조건 확인 필요: {', '.join(sorted(codes))}")
        if not reasons:
            self.write(f"    - {incident.reason or '상세 문맥 정보 없음'}")
        elif not any(re.findall(r"BTT2-[A-Z]\d{2}", reason) for reason in reasons):
            for reason in reasons:
                self.write(f"    - {reason}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "outputs/incident_history"
    )
    parser.add_argument("--codes", nargs="+", help="e.g. BTT2-M10 BTT2-P03")
    parser.add_argument(
        "--context", choices=("RUN_ONLY", "MINIMAL"), default="RUN_ONLY"
    )
    parser.add_argument("--buffer-seconds", type=float, default=120)
    parser.add_argument("--buffer-rows", type=int, default=2048)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument(
        "--live",
        action="store_true",
        help="검증된 센서 행과 실제 사건 변화를 stderr에 즉시 출력",
    )
    args = parser.parse_args()
    try:
        replay_json((), lambda _: None, interval_s=args.interval)
    except ValueError as error:
        parser.error(str(error))
    source_hash = hashlib.sha256()
    with args.csv.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            source_hash.update(chunk)
    source = {
        "path": str(args.csv.resolve()),
        "sha256": source_hash.hexdigest(),
        "context_preset": args.context,
        "assumptions": "SIMULATION ONLY; not verified operational PLC context",
        "input_path": "CsvJsonSource -> JsonTelemetryInput -> HistoryDetector.process",
        "replay_interval_s": args.interval,
        "context_values": {
            "run_cmd": True,
            **(
                {
                    "events_reliable": True,
                    "downstream_ready": True,
                    "tracking_reset": "first row only, if both presence sensors are false",
                }
                if args.context == "MINIMAL"
                else {}
            ),
        },
    }
    with HistoryDetector(
        args.output,
        enabled_codes=set(args.codes) if args.codes else None,
        config=HistoryConfig(
            buffer_seconds=args.buffer_seconds, buffer_rows=args.buffer_rows
        ),
        source=source,
    ) as detector:
        first = True
        live = LiveReplay() if args.live else None
        if live:
            live.write(
                f"[시작] CSV → JSON → 검증 → 탐지/저장 | interval={args.interval}s "
                f"context={args.context} (시뮬레이션 가정)"
            )
            live.write(f"[입력] {args.csv.resolve()}")
            live.write(f"[저장] {detector.run_path}")
            live.write(
                "sensor_time은 원본 시각, PC/elapsed는 재생 시각입니다. Ctrl+C로 중단합니다."
            )

        def handle(record: TelemetryRecord, plc_context):
            nonlocal first
            if live:
                live.received(record)
            context = {"run_cmd": True}
            if args.context == "MINIMAL":
                context.update(
                    events_reliable=True,
                    downstream_ready=True,
                    tracking_reset=(
                        first
                        and not record.infeed_present
                        and not record.outfeed_present
                    ),
                )
            first = False
            changes = detector.process(record, context)
            if live:
                live.processed(changes)
            return changes

        receiver = JsonTelemetryInput(handle)
        input_rows = replay_json(
            CsvJsonSource(args.csv), receiver.receive, interval_s=args.interval
        )
    reader = HistoryReader(detector.run_path)
    reader.validate()
    if live:
        live.write(
            f"[완료] {input_rows}행 처리, HistoryReader 무결성 검증 통과 | {detector.run_path}"
        )
    summary = []
    for incident_id in reader.list_incidents():
        incident = reader.incident(incident_id)
        summary.append(
            {
                "incident_id": incident_id,
                "codes": incident.codes,
                "status": incident.status,
                "events": sum(1 for _ in reader.events(incident_id)),
                "telemetry_rows": sum(1 for _ in reader.telemetry(incident_id)),
                "telemetry_bytes": (detector.run_path / incident_id / "telemetry.jsonl")
                .stat()
                .st_size,
            }
        )
    print(
        json.dumps(
            {
                "run_path": str(detector.run_path),
                "input_rows": input_rows,
                "simulation_assumptions": source,
                "incidents": summary,
                "total_bytes": sum(
                    p.stat().st_size
                    for p in detector.run_path.rglob("*")
                    if p.is_file()
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
