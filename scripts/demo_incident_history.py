"""CSV -> opt-in file history; input/output CLI paths, streaming readback and sizes.

Run: uv run --no-sync python scripts/demo_incident_history.py --help
Default input: data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv
Default output: outputs/incident_history/<unique run>/
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weeing_weeing.contracts import TelemetryRecord  # noqa: E402
from weeing_weeing.detector.interface import (  # noqa: E402
    HistoryConfig,
    HistoryDetector,
    HistoryReader,
)


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
    args = parser.parse_args()
    source_hash = hashlib.sha256()
    with args.csv.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            source_hash.update(chunk)
    source = {
        "path": str(args.csv.resolve()),
        "sha256": source_hash.hexdigest(),
        "context_preset": args.context,
        "assumptions": "SIMULATION ONLY; not verified operational PLC context",
    }
    with HistoryDetector(
        args.output,
        enabled_codes=set(args.codes) if args.codes else None,
        config=HistoryConfig(
            buffer_seconds=args.buffer_seconds, buffer_rows=args.buffer_rows
        ),
        source=source,
    ) as detector:
        with args.csv.open(encoding="utf-8-sig", newline="") as file:
            for index, raw in enumerate(csv.DictReader(file)):
                record = TelemetryRecord.model_validate(raw)
                context = {"run_cmd": True}
                if args.context == "MINIMAL":
                    context.update(
                        events_reliable=True,
                        downstream_ready=True,
                        tracking_reset=(
                            index == 0
                            and not record.infeed_present
                            and not record.outfeed_present
                        ),
                    )
                detector.process(record, context)
    reader = HistoryReader(detector.run_path)
    reader.validate()
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
