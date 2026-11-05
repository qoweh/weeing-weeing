"""멀티 분석의 기본 센서 조회 정책. 원시 표본이나 외부 DB에 직접 접근하지 않는다."""

from weeing_weeing.agent.runtime import RunMemory
from weeing_weeing.agent.sensor_window import UNITS, SensorReader, window_tool
from weeing_weeing.contracts import Incident

FIELD_NAMES = {
    "infeed_present": "입구 센서",
    "outfeed_present": "출구 센서",
    "rpm": "모터 회전 속도",
    "dc_input_current_a": "DC 입력 전류",
    "dc_bus_voltage_v": "DC 버스 전압",
    "motor_housing_temp_c": "모터 외함 온도",
    "de_vibration_rms_g": "구동측 진동 RMS",
    "de_kurtosis": "구동측 첨도",
    "nde_vibration_rms_g": "반구동측 진동 RMS",
    "nde_kurtosis": "반구동측 첨도",
}


def baseline_fields(incident: Incident) -> list[str]:
    fields = [item.field for item in incident.evidence if item.field in UNITS]
    for code in incident.codes:
        if code.startswith("BTT2-P"):
            fields.extend(["infeed_present", "outfeed_present", "rpm"])
        elif code in {"BTT2-M09", "BTT2-M10"}:
            fields.extend(
                [
                    "motor_housing_temp_c",
                    "dc_input_current_a",
                    "rpm",
                    "de_vibration_rms_g",
                    "nde_vibration_rms_g",
                ]
            )
        elif code.startswith("BTT2-M") and int(code[-2:]) >= 11:
            fields.extend(
                [
                    "de_vibration_rms_g",
                    "de_kurtosis",
                    "nde_vibration_rms_g",
                    "nde_kurtosis",
                    "rpm",
                    "motor_housing_temp_c",
                ]
            )
        elif code.startswith("BTT2-M"):
            fields.extend(["rpm", "dc_input_current_a", "dc_bus_voltage_v"])
        else:
            fields.extend(UNITS)
    return list(dict.fromkeys(fields))[:10]


def ensure_baseline(
    incident: Incident, reader: SensorReader | None, memory: RunMemory
) -> bool:
    """최대 120초의 저장 표본을 한 번 조회한다. 완료/빈 결과는 재시도 시 재사용한다."""
    if any(
        window.get("purpose") == "baseline" for window in memory.sensor_windows.values()
    ):
        return False
    if reader is None:
        return False
    window_tool(incident, reader).handler(
        {
            "before_seconds": 120,
            "after_seconds": 0,
            "fields": baseline_fields(incident),
        },
        memory,
    )
    window = next(reversed(memory.sensor_windows.values()))
    window["purpose"] = "baseline"
    return True


def baseline_facts(memory: RunMemory) -> list[str]:
    lines = []
    for window in memory.sensor_windows.values():
        if window.get("purpose") != "baseline":
            continue
        lines.append(
            f"기본 센서 이력: 저장 표본 {window['sample_count']}개. 관측 범위와 공백은 센서 관측 범위에서 확인한다."
        )
        for name, field in window["fields"].items():
            stats = field["statistics"]
            parts = [
                f"유효 {stats['valid_count']}개",
                f"결측 {stats['missing_count']}개",
            ]
            for key, label in (
                ("first", "처음"),
                ("last", "마지막"),
                ("min", "최소"),
                ("max", "최대"),
                ("delta", "변화량"),
            ):
                if key in stats:
                    value = stats[key]
                    display = (
                        ("감지" if value else "미감지")
                        if isinstance(value, bool)
                        else f"{value} {field['unit']}"
                    )
                    parts.append(f"{label} {display}")
            lines.append(f"{FIELD_NAMES.get(name, name)}: {', '.join(parts)}")
    return lines
