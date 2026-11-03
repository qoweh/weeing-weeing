"""Streaming CSV wire-message source and synchronous, monotonic replay."""

import csv
import json
import math
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from weeing_weeing.contracts.telemetry import COLUMNS
from weeing_weeing.ingest.json_input import (
    BOOLEANS,
    OPTIONAL_SENSORS,
    SENSORS,
    TelemetryInputError,
    parse_telemetry_json,
)


class CsvTelemetryError(TelemetryInputError):
    """CSV input failure with physical line number, without source values."""


class CsvJsonSource:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __iter__(self) -> Iterator[str]:
        with self.path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file, strict=True)
            try:
                header = next(reader, [])
                if len(header) != len(COLUMNS) or set(header) != set(COLUMNS):
                    raise CsvTelemetryError("CSV line 1: invalid telemetry header")
                for values in reader:
                    if len(values) != len(header):
                        raise ValueError
                    data = dict(zip(header, values))
                    for name in BOOLEANS:
                        cell = data[name].strip().lower()
                        if cell not in ("true", "false"):
                            raise ValueError
                        data[name] = cell == "true"
                    for name in SENSORS:
                        cell = data[name].strip()
                        data[name] = (
                            None
                            if not cell and name in OPTIONAL_SENSORS
                            else float(cell)
                        )
                    message = json.dumps(data, ensure_ascii=False, allow_nan=False)
                    parse_telemetry_json(message)
                    yield message
            except CsvTelemetryError:
                raise
            except (ValueError, OverflowError, csv.Error, UnicodeError):
                raise CsvTelemetryError(
                    f"CSV line {max(reader.line_num, 1)}: invalid telemetry row or encoding"
                ) from None


def replay_json(
    messages: Iterable[str | bytes],
    receive: Callable[[str | bytes], object],
    interval_s: float = 0.5,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """First delivery is immediate; slow processing applies backpressure, never drops.

    Deadlines are relative to the previous delivery start. Missed slots do not
    create a catch-up burst. Input timestamps and identities remain untouched.
    """
    if (
        isinstance(interval_s, bool)
        or not isinstance(interval_s, (int, float))
        or not math.isfinite(interval_s)
        or interval_s < 0
    ):
        raise ValueError("interval_s must be finite and nonnegative")
    count = 0
    previous_start = None
    for message in messages:
        if interval_s and previous_start is not None:
            remaining = previous_start + interval_s - monotonic()
            while remaining > 0:
                sleep(remaining)
                remaining = previous_start + interval_s - monotonic()
        previous_start = monotonic()
        receive(message)
        count += 1
    return count
