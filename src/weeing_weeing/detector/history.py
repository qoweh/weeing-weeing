"""Opt-in, sequential file history. No detection rules or common contracts live here."""

import hashlib
import json
import math
import os
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from weeing_weeing.contracts import Incident, IncidentStatus, TelemetryRecord
from weeing_weeing.contracts.codes import RULE_VERSION
from weeing_weeing.detector.builtin_rules import NUMERIC_RULES
from weeing_weeing.detector.rule_engine import RuleDetector

HISTORY_SCHEMA_VERSION = "1.0.0"


class HistoryError(RuntimeError):
    """History is incomplete, incompatible, corrupt, or no longer writable."""


def _encode(value):
    if isinstance(value, BaseModel):
        return _encode(value.model_dump())
    if hasattr(value, "__dataclass_fields__"):
        return _encode(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return {"$float": str(value)}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _restore(value):
    if isinstance(value, dict):
        if set(value) == {"$float"}:
            return float(value["$float"])
        return {k: _restore(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_restore(v) for v in value]
    return value


def _bytes(value, *, canonical=False):
    return (
        json.dumps(
            _encode(value), ensure_ascii=False, allow_nan=False, sort_keys=canonical
        )
        + "\n"
    ).encode("utf-8")


def _atomic(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as file:
        file.write(_bytes(value))
        file.flush()
        os.fsync(file.fileno())
    # Windows virus scanners/readers can briefly hold the destination open.
    # Only retry this idempotent replacement, never the detection/input itself.
    for attempt in range(6):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if os.name != "nt" or attempt == 5:
                raise
            time.sleep(0.01 * 2**attempt)


def _load(path):
    try:
        return _restore(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        raise HistoryError(f"Cannot read {path}: {exc}") from exc


@dataclass(frozen=True)
class HistoryConfig:
    buffer_seconds: float = 120
    buffer_rows: int = 2048
    max_assets: int = 64
    max_records: int = 100_000

    def __post_init__(self):
        if not math.isfinite(self.buffer_seconds) or self.buffer_seconds <= 0:
            raise ValueError("buffer_seconds must be finite and positive")
        for value in (self.buffer_rows, self.max_assets, self.max_records):
            if type(value) is not int or value <= 0:
                raise ValueError("row/asset/record limits must be positive integers")


class _Collection:
    def __init__(self, path, incident, entries):
        self.path = path
        self.incident = incident
        self.counts = {"telemetry": 0, "events": 0}
        self.hashes = {name: hashlib.sha256() for name in self.counts}
        self.sizes = dict(self.counts)
        self.meta = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "incident_id": incident.incident_id,
            "requested_start": incident.first_detected_at,
            "actual_start": entries[0]["record"]["timestamp"],
            "candidate_prefix_missing": (
                datetime.fromisoformat(entries[0]["record"]["timestamp"])
                > incident.first_detected_at
            ),
            "gap_count": 0,
            "sampling_discontinuity_count": 0,
            "collection_end_reason": None,
        }
        self.path.mkdir(exist_ok=False)
        for name in self.counts:
            (path / f"{name}.jsonl").touch(exist_ok=False)

    def append(self, name, value):
        data = _bytes(value)
        with (self.path / f"{name}.jsonl").open("ab") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        self.counts[name] += 1
        self.hashes[name].update(data)
        self.sizes[name] += len(data)

    def telemetry(self, entry, *, candidate=False):
        code = self.incident.codes[0]
        details = entry["rules"][code]
        value = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "incident_id": self.incident.incident_id,
            "record": entry["record"],
            "annotation": {
                **details,
                "collection_phase": "candidate" if candidate else details["phase"],
                "gap_seconds": entry["gap_seconds"],
                "input_delta_seconds": entry["input_delta_seconds"],
                "plc_context": entry["plc_context"],
            },
        }
        self.append("telemetry", value)
        self.meta["actual_end"] = entry["record"]["timestamp"]
        if entry["gap_seconds"] is not None:
            self.meta["gap_count"] += 1
        if (entry["input_delta_seconds"] or 0) > 1:
            self.meta["sampling_discontinuity_count"] += 1

    def checkpoint(self, reason=None):
        if reason is not None:
            self.meta["collection_end_reason"] = reason
        _atomic(self.path / "incident.json", self.incident)
        _atomic(
            self.path / "metadata.json",
            {
                **self.meta,
                "files": {
                    name: {
                        "rows": self.counts[name],
                        "bytes": self.sizes[name],
                        "sha256": self.hashes[name].hexdigest(),
                    }
                    for name in self.counts
                },
                "incident_sha256": hashlib.sha256(_bytes(self.incident)).hexdigest(),
            },
        )


class HistoryDetector:
    """Fresh Detector + bounded lookback + file writer. Single process, serial calls.

    On any processing/write error this instance is poisoned: do not replay the
    input into its already advanced evaluator. Start a new run instead.
    """

    def __init__(
        self,
        output: Path | str = "outputs/incident_history",
        *,
        enabled_codes=None,
        policies=None,
        config: HistoryConfig | None = None,
        source: dict | None = None,
    ):
        self.config = config or HistoryConfig()
        self._detector = RuleDetector(enabled_codes=enabled_codes, policies=policies)
        self.run_path = Path(output) / f"run-{uuid4().hex}"
        self.run_path.mkdir(parents=True, exist_ok=False)
        self._buffers = {}
        self._previous = {}
        self._seen = set()
        self._open = {}
        self._closed = False
        self._failed = False
        self._manifest = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "status": "running",
            "completed": False,
            "created_at": datetime.now(timezone.utc),
            "source": source or {},
            "config": self.config,
            "detector": {
                "rule_version": RULE_VERSION,
                "enabled_codes": sorted(self._detector.evaluator.enabled_codes),
                "policies": self._detector.evaluator.policies,
                "numeric_rules": NUMERIC_RULES,
                "gap_interrupt_seconds": 2,
                "implementation_sha256": {
                    name: hashlib.sha256(
                        Path(__file__).with_name(name).read_bytes()
                    ).hexdigest()
                    for name in (
                        "builtin_rules.py",
                        "rule_engine.py",
                        "incident_manager.py",
                    )
                },
            },
            "accepted_records": 0,
            "pending_input": None,
        }
        self._save_manifest()

    def _save_manifest(self):
        _atomic(self.run_path / "manifest.json", self._manifest)

    def _ready(self):
        if self._failed or self._closed:
            raise HistoryError("Run is failed/closed; detection restart is unsupported")

    def process(self, record, plc_context=None, *, assessments=None):
        self._ready()
        # Serialize before evaluation; contexts unsupported by JSON fail explicitly.
        try:
            return self._process(record, plc_context or {}, assessments)
        except Exception:
            self._failed = True
            self._manifest.update(status="failed", completed=False)
            try:
                self._save_manifest()
            except OSError:
                pass  # the previous durable manifest remains running/pending
            raise

    def _process(self, record, context, assessments):
        key = record.process_id, record.asset_id
        encoded = _bytes(
            {"record": record, "context": context, "assessments": assessments},
            canonical=True,
        )
        previous = self._previous.get(key)
        if previous is not None and encoded == previous[1]:
            return []
        identity = (*key, record.record_id)
        if identity in self._seen:
            raise ValueError("Reused record_id or conflicting duplicate input")
        if previous and record.timestamp <= previous[0]:
            raise ValueError("Non-increasing timestamp")
        if len(self._seen) >= self.config.max_records:
            raise HistoryError("Run record limit reached; start a new run")
        if key not in self._buffers and len(self._buffers) >= self.config.max_assets:
            raise HistoryError("Run asset limit reached")
        self._manifest["pending_input"] = {
            "process_id": record.process_id,
            "asset_id": record.asset_id,
            "record_id": record.record_id,
            "timestamp": record.timestamp,
        }
        self._save_manifest()
        frame = self._detector.process_frame(record, context, assessments=assessments)
        if not frame.accepted:
            raise HistoryError("Unexpected unaccepted input")
        rules = {
            item.rule_code: {"assessment": item, **frame.progress[item.rule_code]}
            for item in frame.assessments
        }
        entry = _encode(
            {
                "record": record,
                "rules": rules,
                "gap_seconds": frame.gap_seconds,
                "input_delta_seconds": (
                    (record.timestamp - previous[0]).total_seconds()
                    if previous
                    else None
                ),
                "plc_context": context,
            }
        )
        buffer = self._buffers.setdefault(key, deque())
        buffer.append(entry)
        while (
            len(buffer) > self.config.buffer_rows
            or (
                record.timestamp
                - datetime.fromisoformat(buffer[0]["record"]["timestamp"])
            ).total_seconds()
            > self.config.buffer_seconds
        ):
            buffer.popleft()
        changed = {item.incident_id: item for item in frame.incidents}
        new_ids = set()
        for incident in frame.incidents:
            if incident.incident_id not in self._open:
                entries = [
                    e
                    for e in buffer
                    if datetime.fromisoformat(e["record"]["timestamp"])
                    >= incident.first_detected_at
                ]
                collection = _Collection(
                    self.run_path / incident.incident_id, incident, entries
                )
                self._open[incident.incident_id] = collection
                new_ids.add(incident.incident_id)
                for buffered in entries:
                    collection.telemetry(
                        buffered,
                        candidate=(
                            datetime.fromisoformat(buffered["record"]["timestamp"])
                            < incident.confirmed_at
                        ),
                    )
        for incident_id, collection in list(self._open.items()):
            if (collection.incident.process_id, collection.incident.asset_id) != key:
                continue
            if incident_id not in new_ids:
                collection.telemetry(entry)
            incident = changed.get(incident_id)
            if incident is not None:
                old = collection.incident
                kind = (
                    "confirmed"
                    if incident_id in new_ids
                    else "recovered"
                    if incident.status == IncidentStatus.RECOVERED
                    else "escalated"
                    if old.severity != incident.severity
                    else "updated"
                )
                if incident_id in new_ids or old != incident:
                    collection.append(
                        "events",
                        {
                            "schema_version": HISTORY_SCHEMA_VERSION,
                            "incident_id": incident_id,
                            "kind": kind,
                            "timestamp": record.timestamp,
                            "record_id": record.record_id,
                            "incident": incident,
                        },
                    )
                collection.incident = incident.model_copy(deep=True)
            recovered = collection.incident.status == IncidentStatus.RECOVERED
            collection.checkpoint("recovered" if recovered else None)
            if recovered:
                del self._open[incident_id]
        self._seen.add(identity)
        self._previous[key] = (record.timestamp, encoded)
        self._manifest["accepted_records"] += 1
        self._manifest["pending_input"] = None
        self._save_manifest()
        return frame.incidents

    def active_incidents(self):
        return self._detector.active_incidents()

    def close(self, reason="input_end"):
        if self._closed:
            return
        self._ready()
        try:
            for collection in self._open.values():
                collection.checkpoint(reason)
            self._manifest.update(
                status="completed",
                completed=True,
                end_reason=reason,
                ended_at=datetime.now(timezone.utc),
            )
            self._save_manifest()
            self._closed = True
        except Exception:
            self._failed = True
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.close()
        else:
            self._failed = True
            self._manifest.update(status="failed", completed=False)
            try:
                self._save_manifest()
            except OSError:
                pass


class HistoryReader:
    """Strict, streaming reader. validate() detects interrupted multi-file writes."""

    def __init__(self, run_path):
        self.run_path = Path(run_path)
        self.manifest = _load(self.run_path / "manifest.json")
        self._version(self.manifest)

    @staticmethod
    def _version(value):
        if value.get("schema_version") != HISTORY_SCHEMA_VERSION:
            raise HistoryError("Unsupported history schema_version")

    def _path(self, incident_id):
        if not incident_id.startswith("INC-") or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for c in incident_id
        ):
            raise HistoryError("Invalid incident_id")
        return self.run_path / incident_id

    def list_incidents(self):
        return sorted(p.name for p in self.run_path.glob("INC-*") if p.is_dir())

    def incident(self, incident_id):
        return Incident.model_validate(_load(self._path(incident_id) / "incident.json"))

    def metadata(self, incident_id):
        value = _load(self._path(incident_id) / "metadata.json")
        self._version(value)
        return value

    def _lines(self, incident_id, name):
        path = self._path(incident_id) / f"{name}.jsonl"
        try:
            with path.open("rb") as file:
                for number, line in enumerate(file, 1):
                    if not line.endswith(b"\n"):
                        raise ValueError(f"Unterminated line {number}")
                    value = _restore(json.loads(line))
                    self._version(value)
                    if value["incident_id"] != incident_id:
                        raise ValueError(f"Wrong incident on line {number}")
                    yield value
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HistoryError(f"Corrupt {path}: {exc}") from exc

    def events(self, incident_id):
        for event in self._lines(incident_id, "events"):
            Incident.model_validate(event["incident"])
            yield event

    def telemetry(self, incident_id):
        previous = None
        for entry in self._lines(incident_id, "telemetry"):
            record = TelemetryRecord.model_validate(entry["record"])
            if previous is not None and record.timestamp <= previous:
                raise HistoryError("Telemetry is not strictly time ordered")
            previous = record.timestamp
            yield entry

    def validate(self):
        if list(self.run_path.glob("*.tmp")):
            raise HistoryError("Unfinished manifest write")
        if not self.manifest.get("completed") or self.manifest.get("pending_input"):
            raise HistoryError(
                "Run is incomplete/failed; inspect partial data explicitly"
            )
        for incident_id in self.list_incidents():
            path = self._path(incident_id)
            if list(path.glob("*.tmp")):
                raise HistoryError(f"Unfinished atomic write: {incident_id}")
            meta = self.metadata(incident_id)
            latest = self.incident(incident_id)
            if latest.incident_id != incident_id:
                raise HistoryError("Incident identity mismatch")
            for name, iterator in (
                ("events", self.events),
                ("telemetry", self.telemetry),
            ):
                expected = meta["files"][name]
                count = sum(1 for _ in iterator(incident_id))
                digest = hashlib.sha256()
                size = 0
                with (path / f"{name}.jsonl").open("rb") as file:
                    for chunk in iter(lambda: file.read(65536), b""):
                        digest.update(chunk)
                        size += len(chunk)
                if (count, size, digest.hexdigest()) != (
                    expected["rows"],
                    expected["bytes"],
                    expected["sha256"],
                ):
                    raise HistoryError(f"Checkpoint mismatch: {incident_id}/{name}")
            if (
                hashlib.sha256((path / "incident.json").read_bytes()).hexdigest()
                != meta["incident_sha256"]
            ):
                raise HistoryError("Incident checkpoint mismatch")
        return True
