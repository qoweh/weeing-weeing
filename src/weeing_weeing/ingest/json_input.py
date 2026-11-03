"""Strict wire input; detection and persistence are injected by the caller."""

import json
import math
from datetime import datetime
from typing import Any, Callable, Generic, TypeVar

from pydantic import ValidationError

from weeing_weeing.contracts import TelemetryRecord
from weeing_weeing.contracts.telemetry import COLUMNS, SCHEMA_VERSION

DEFAULT_MAX_MESSAGE_BYTES = 64 * 1024
IDENTIFIERS = ("record_id", "process_id", "asset_id", "schema_version")
BOOLEANS = ("infeed_present", "outfeed_present")
OPTIONAL_SENSORS = ("dc_input_current_a", "motor_housing_temp_c")
SENSORS = COLUMNS[7:]
T = TypeVar("T")


class TelemetryInputError(ValueError):
    """Invalid wire input. Messages never include payload values."""


def _check_limit(limit: int) -> None:
    if type(limit) is not int or limit <= 0:
        raise ValueError("max_message_bytes must be a positive integer")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TelemetryInputError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(_value):
    raise TelemetryInputError("Non-finite JSON number")


def parse_telemetry_json(
    message: str | bytes, *, max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES
) -> TelemetryRecord:
    """Validate exactly one complete 15-field object without scalar coercion."""
    _check_limit(max_message_bytes)
    if not isinstance(message, (str, bytes)):
        raise TelemetryInputError("Expected JSON text or UTF-8 bytes")
    try:
        # Reject oversized text before allocating its UTF-8 representation.
        if len(message) > max_message_bytes:
            raise TelemetryInputError("Message exceeds byte limit")
        encoded = message.encode("utf-8") if isinstance(message, str) else message
        if len(encoded) > max_message_bytes:
            raise TelemetryInputError("Message exceeds byte limit")
        data = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=_constant,
        )
        if not isinstance(data, dict) or set(data) != set(COLUMNS):
            raise TelemetryInputError("Expected exactly the 15 telemetry fields")
        for name in IDENTIFIERS:
            if not isinstance(data[name], str) or not data[name].strip():
                raise TelemetryInputError(f"Expected nonblank string: {name}")
        if data["schema_version"] != SCHEMA_VERSION:
            raise TelemetryInputError("Unsupported schema_version")
        for name in BOOLEANS:
            if type(data[name]) is not bool:
                raise TelemetryInputError(f"Expected JSON boolean: {name}")
        for name in SENSORS:
            value = data[name]
            if value is None and name in OPTIONAL_SENSORS:
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise TelemetryInputError(f"Expected finite JSON number: {name}")
        if not isinstance(data["timestamp"], str):
            raise TelemetryInputError("Expected timezone-aware timestamp string")
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return TelemetryRecord.model_validate(data, strict=True)
    except TelemetryInputError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError, ValidationError):
        raise TelemetryInputError("Invalid telemetry JSON or timestamp") from None


class JsonTelemetryInput(Generic[T]):
    """One stream, sequential calls; handler failures propagate without retry."""

    def __init__(
        self,
        handler: Callable[[TelemetryRecord, dict[str, Any] | None], T],
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
    ) -> None:
        _check_limit(max_message_bytes)
        self._handler = handler
        self.max_message_bytes = max_message_bytes

    def receive(
        self, message: str | bytes, plc_context: dict[str, Any] | None = None
    ) -> T:
        record = parse_telemetry_json(message, max_message_bytes=self.max_message_bytes)
        return self._handler(record, plc_context)
