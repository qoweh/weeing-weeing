"""명시적 UNREAL_STATE 수신 경계. 기존 15필드 입력 파서는 변경하지 않는다."""

import json

from pydantic import ValidationError

from weeing_weeing.contracts import CODES, SimulatorOperatingContext
from weeing_weeing.ingest.interface import TelemetryInputError, parse_telemetry_json

EXCLUDED = {
    "BTT2-M04": "정확한 1초 격자·21표본 미제공",
    "BTT2-M19": "승인된 정상 기준 미등록",
}
ENABLED = set(CODES) - EXCLUDED.keys()
COVERAGE = {"source": "UNREAL_SIMULATOR", "excluded": EXCLUDED}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def parse_simulator_frame(message):
    try:
        if not isinstance(message, (str, bytes)) or len(message) > 65536:
            raise ValueError("Invalid frame size")
        encoded = message.encode("utf-8") if isinstance(message, str) else message
        if len(encoded) > 65536:
            raise ValueError("Invalid frame size")
        data = json.loads(encoded, object_pairs_hook=_object)
        if (
            set(data) != {"message_type", "telemetry", "context"}
            or data["message_type"] != "telemetry_with_context_v1"
        ):
            raise ValueError("Invalid envelope")
        wire = json.dumps(data["telemetry"], ensure_ascii=False)
        record = parse_telemetry_json(wire)
        source = SimulatorOperatingContext.model_validate(data["context"])
        times = [e.at for e in source.events] + [p.entered_at for p in source.pending]
        times += [
            at
            for at in (
                source.run_started_at,
                source.last_infeed_at,
                source.last_outfeed_at,
            )
            if at is not None
        ]
        if any(at > record.timestamp for at in times):
            raise ValueError("Future source timestamp")
        context = {
            "run_cmd": source.run_cmd,
            "run_started_at": source.run_started_at,
            "simulation_run_age_seconds": (
                source.simulation_seconds - source.run_started_simulation_seconds
                if source.run_started_simulation_seconds is not None
                else None
            ),
            "fixed_speed": source.fixed_speed,
            "same_load": source.same_load,
            "vibration_comparable": source.vibration_comparable,
            "recipe_id": source.recipe_id,
            "config_version": source.config_version,
            "continuous_infeed": source.run_cmd,
            "downstream_ready": source.downstream_ready,
            "source_tracking": source.model_dump(),
            "quality_rule_codes": sorted(ENABLED),
        }
        return wire, context
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        RecursionError,
        ValidationError,
    ):
        raise TelemetryInputError("Invalid simulator telemetry context") from None
