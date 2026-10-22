"""CSV를 공통 룰 엔진으로 평가하고 변경된 Incident를 JSON으로 저장한다.

입력: data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv (원본 유지)
출력: outputs/incidents/<사건 ID>/<순번>_<상태>_<등급>.json
실행: uv run --no-sync python scripts/demo_incident_json.py
RUN 및 입력 유효성을 가정하는 DEMO다. 추가 문맥은 추측하지 않는다.
"""

import csv
import sys
from pathlib import Path

# 프로젝트를 설치하지 않는 팀 환경에서도 저장소 소스를 직접 사용한다.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weeing_weeing.contracts import Incident, TelemetryRecord  # noqa: E402
from weeing_weeing.detector.interface import RuleDetector  # noqa: E402

CSV_PATH = ROOT / "data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv"


def show_and_save(
    directory: Path, filename: str, label: str, incident: Incident
) -> None:
    text = incident.model_dump_json(indent=2)
    path = directory / filename
    path.write_text(text + "\n", encoding="utf-8")
    print(f"\n[{label}] {path.relative_to(ROOT)}")
    print(text)


def main() -> None:
    detector = RuleDetector()
    sequence: dict[str, int] = {}
    print("공통 룰 판정 DEMO — RUN·입력 유효성 가정, 추가 문맥 미확보는 Unknown")
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            record = TelemetryRecord.model_validate(row)
            for incident in detector.process(record, {"run_cmd": True}):
                directory = ROOT / "outputs" / "incidents" / incident.incident_id
                count = sequence.get(incident.incident_id, 0) + 1
                if count == 1:
                    directory.mkdir(parents=True, exist_ok=False)
                sequence[incident.incident_id] = count
                label = f"{incident.status.value}_{incident.severity.value}"
                show_and_save(directory, f"{count:02d}_{label}.json", label, incident)


if __name__ == "__main__":
    main()
