"""CSV와 가짜 룰 판정으로 Incident JSON을 출력하고 저장한다.

입력: data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv (원본 유지)
출력: outputs/incidents/<사건 ID>/01_confirmed.json, 02_updated.json, 03_recovered.json
실행: uv run --no-sync python scripts/demo_incident_json.py
발생·확정·회복 시점은 출력 시연용이며 실제 룰 판정 결과가 아니다.
"""

import csv
import sys
from pathlib import Path

# 프로젝트를 설치하지 않는 팀 환경에서도 저장소 소스를 직접 사용한다.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weeing_weeing.contracts import (  # noqa: E402
    Incident,
    SensorEvidence,
    Severity,
    TelemetryRecord,
)
from weeing_weeing.detector.incident_manager import IncidentManager  # noqa: E402

CSV_PATH = ROOT / "data/telemetry/battery_tray_transfer_telemetry_v3_15cols.csv"
SENSOR_UNITS = {
    "infeed_present": None,
    "outfeed_present": None,
    "rpm": "rpm",
    "dc_input_current_a": "A",
    "dc_bus_voltage_v": "V",
    "motor_housing_temp_c": "℃",
    "de_vibration_rms_g": "g",
    "de_kurtosis": None,
    "nde_vibration_rms_g": "g",
    "nde_kurtosis": None,
}


def sensor_evidence(record: TelemetryRecord) -> list[SensorEvidence]:
    """눈으로 확인할 수 있도록 해당 행의 전체 센서값을 기록한다."""
    return [
        SensorEvidence(
            field=field,
            value=getattr(record, field),
            unit=unit,
            valid=getattr(record, field) is not None,
            observed=f"{record.timestamp.isoformat()} / {record.record_id}",
            note="CSV 원본 센서값. 룰 판정은 시연용 가짜 입력입니다.",
        )
        for field, unit in SENSOR_UNITS.items()
    ]


def show_and_save(
    directory: Path, filename: str, label: str, incident: Incident
) -> None:
    text = incident.model_dump_json(indent=2)
    path = directory / filename
    path.write_text(text + "\n", encoding="utf-8")
    print(f"\n[{label}] {path.relative_to(ROOT)}")
    print(text)


def main() -> None:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as file:
        records = [TelemetryRecord.model_validate(row) for row in csv.DictReader(file)]

    manager = IncidentManager()
    # 테스트에서만 20초 후보 시작, 23초 확정, 30초 회복으로 가정한다.
    confirmed = manager.confirm(
        records[23],
        "BTT2-P03",
        severity=Severity.ERROR,
        first_detected_at=records[20].timestamp,
        evidence=sensor_evidence(records[23]),
    )
    for record in records[24:30]:
        updated = manager.update(record, "BTT2-P03", evidence=sensor_evidence(record))
    recovered = manager.recover(records[30], "BTT2-P03")

    directory = ROOT / "outputs" / "incidents" / confirmed.incident_id
    directory.mkdir(parents=True, exist_ok=False)
    print("Incident JSON 출력 시연 — CSV 센서값 + 가짜 룰 판정")
    print("실제 이상 탐지·Agent 호출은 수행하지 않습니다.")
    show_and_save(directory, "01_confirmed.json", "1. 이상 확정", confirmed)
    show_and_save(directory, "02_updated.json", "2. 이상 지속", updated)
    show_and_save(directory, "03_recovered.json", "3. 회복", recovered)
    print(
        "\n세 파일은 같은 사건 ID의 시점별 기록입니다. 회복 근거는 마지막 이상값을 유지합니다."
    )


if __name__ == "__main__":
    main()
