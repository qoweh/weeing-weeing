"""유한 큐를 사용하는 관찰 전용 추론. Detector/DB/Agent/PLC를 호출하지 않는다."""

import hashlib
import json
import logging
import re
import time
from collections import deque
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Lock, Thread

logger = logging.getLogger("uvicorn.error.ml")


class LivePredictionService:
    def __init__(
        self,
        *,
        enabled,
        model_path,
        model_sha256,
        output_dir,
        predictor_loader=None,
        queue_size=8,
        stale_seconds=3,
    ):
        self.enabled = enabled
        self.model_path = Path(model_path)
        self.model_sha256 = model_sha256
        self.output_dir = Path(output_dir)
        self.loader = predictor_loader
        self.queue = Queue(maxsize=queue_size)
        self.stale_seconds = stale_seconds
        self.lock = Lock()
        self.thread = None
        self.stopping = False
        self.loaded = False
        self.generation = 0
        self.run_id = None
        self.connected = False
        self.result_clock = None
        self.model_version = None
        self.counters = {
            "submitted": 0,
            "completed": 0,
            "dropped": 0,
            "errors": 0,
            "log_errors": 0,
        }
        self.latest = {
            "status": "initializing" if enabled else "disabled",
            "input_valid": False,
            "probabilities": None,
        }
        self.events = deque(maxlen=200)

    def start(self):
        if self.enabled:
            self.thread = Thread(target=self._work, name="future-error-ml", daemon=True)
            self.thread.start()
        return self

    def stop(self):
        with self.lock:
            self.stopping = True
            self.connected = False
        if self.thread:
            self.thread.join(timeout=5)

    def begin(self, run_id):
        with self.lock:
            self.generation += 1
            self.run_id = run_id
            self.connected = True
            self.result_clock = None
            self.events.clear()
            if self.loaded:
                self.latest = {
                    "status": "not_ready",
                    "reason": "insufficient_history",
                    "input_valid": False,
                    "probabilities": None,
                }

    def end(self, run_id):
        with self.lock:
            if self.run_id == run_id:
                self.generation += 1
                self.connected = False

    def submit(self, run_id, record, active_error_codes):
        with self.lock:
            if (
                not self.enabled
                or not self.loaded
                or self.stopping
                or not self.connected
                or run_id != self.run_id
            ):
                return
            item = (
                self.generation,
                run_id,
                record,
                list(active_error_codes),
                time.monotonic(),
            )
            try:
                self.queue.put_nowait(item)
                self.counters["submitted"] += 1
            except Full:
                # 건너뛴 표본이 있는 이력을 정상으로 취급하지 않는다. 새 세대로 버퍼 초기화.
                self.generation += 1
                self.counters["dropped"] += 1
                self.result_clock = None
                self.latest = {
                    "status": "invalid_input",
                    "reason": "queue_overflow",
                    "input_valid": False,
                    "probabilities": None,
                }

    def snapshot(self):
        with self.lock:
            return self._snapshot_locked()

    def recent_snapshot(self, limit=50):
        with self.lock:
            return {
                "state": self._snapshot_locked(),
                "items": deepcopy(list(self.events)[-limit:]),
            }

    def _snapshot_locked(self):
        age = (
            None if self.result_clock is None else time.monotonic() - self.result_clock
        )
        stale = not self.connected or age is None or age > self.stale_seconds
        result = deepcopy(self.latest)
        usable = (
            not stale
            and result.get("status") == "ready"
            and result.get("input_valid", False)
            and result.get("evaluation_eligible", False)
            and not result.get("deadline_exceeded", False)
        )
        return {
            "enabled": self.enabled,
            "model_loaded": self.loaded,
            "model_version": self.model_version,
            "run_id": self.run_id,
            "producer_connected": self.connected,
            "stale": stale,
            "age_seconds": age,
            "prediction_usable": usable,
            "counters": dict(self.counters),
            "queue_depth": self.queue.qsize(),
            "prediction": result,
        }

    def recent(self, limit=50):
        with self.lock:
            return deepcopy(list(self.events)[-limit:])

    def _load(self):
        # 이미지에 모델과 함께 고정한 manifest를 사용해 이미지 롤백 시 해시도 복구한다.
        expected = (
            self.model_sha256
            or json.loads(
                self.model_path.with_name("manifest.json").read_text(encoding="utf-8")
            )["sha256"]
        )
        if not re.fullmatch("[0-9a-f]{64}", expected):
            raise ValueError("A pinned lowercase SHA-256 is required")
        if hashlib.sha256(self.model_path.read_bytes()).hexdigest() != expected:
            raise ValueError("Model checksum mismatch")
        if self.loader:
            return self.loader(self.model_path)
        from .interface import FutureErrorPredictor

        return FutureErrorPredictor.load(self.model_path)

    def _publish(self, generation, run_id, result, received_clock=None):
        with self.lock:
            if (
                generation != self.generation
                or run_id != self.run_id
                or not self.connected
            ):
                return
            result = {"run_id": run_id, **result}
            self.latest = result
            self.result_clock = (
                received_clock if received_clock is not None else time.monotonic()
            )
            self.counters["completed"] += 1
            self.events.append(deepcopy(result))
        # 파일 I/O도 ML 스레드에서만 수행한다. JSONL은 실행당 최대 10MiB로 회전한다.
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            safe_run = hashlib.sha256(run_id.encode()).hexdigest()[:16]
            path = self.output_dir / f"{safe_run}.jsonl"
            if path.exists() and path.stat().st_size > 10 * 1024 * 1024:
                path.replace(path.with_suffix(".previous.jsonl"))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {"run_id": run_id, **result},
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    + "\n"
                )
        except (OSError, ValueError):
            with self.lock:
                self.counters["log_errors"] += 1
            logger.warning("ML prediction log unavailable")

    def _work(self):
        try:
            predictor = self._load()
            with self.lock:
                self.loaded = True
                self.model_version = predictor.metadata["model_version"]
                self.latest = {
                    "status": "not_ready",
                    "reason": "insufficient_history",
                    "input_valid": False,
                    "probabilities": None,
                }
            logger.info("ML model loaded version=%s", self.model_version)
        except Exception as error:
            with self.lock:
                self.counters["errors"] += 1
                self.latest = {
                    "status": "model_error",
                    "reason": "model_load_failed",
                    "input_valid": False,
                    "probabilities": None,
                }
            logger.error("ML model load failed type=%s", type(error).__name__)
            return
        buffer = deque(maxlen=256)
        previous_generation = None
        while not self.stopping:
            try:
                generation, run_id, record, error_codes, queued_at = self.queue.get(
                    timeout=0.1
                )
            except Empty:
                continue
            try:
                with self.lock:
                    current = (
                        generation == self.generation
                        and run_id == self.run_id
                        and self.connected
                    )
                if not current:
                    continue
                if generation != previous_generation:
                    buffer.clear()
                    previous_generation = generation
                started = time.monotonic()
                timestamp = datetime.fromisoformat(
                    record["timestamp"].replace("Z", "+00:00")
                )
                if timestamp.tzinfo is None:
                    raise ValueError("aware timestamp required")
                if started - queued_at > 1:
                    buffer.clear()
                    result = {
                        "status": "invalid_input",
                        "reason": "processing_lag",
                        "input_valid": False,
                        "probabilities": None,
                    }
                elif buffer and timestamp <= buffer[-1][0]:
                    # 중복·역순 표본은 재사용하지 않고 이력을 초기화한다.
                    buffer.clear()
                    result = {
                        "status": "invalid_input",
                        "reason": "timestamp_order",
                        "input_valid": False,
                        "probabilities": None,
                    }
                else:
                    buffer.append((timestamp, record))
                    left = timestamp - timedelta(seconds=30)
                    while len(buffer) > 1 and buffer[1][0] <= left:
                        buffer.popleft()
                    result = predictor.predict([row for _, row in buffer])
                result.update(
                    reference_time=timestamp.astimezone(UTC).isoformat(),
                    model_version=self.model_version,
                    record_id=record["record_id"],
                    process_id=record["process_id"],
                    asset_id=record["asset_id"],
                    processed_at=datetime.now(UTC).isoformat(),
                    inference_ms=(time.monotonic() - started) * 1000,
                    queue_wait_ms=(started - queued_at) * 1000,
                    processing_latency_ms=(time.monotonic() - queued_at) * 1000,
                    deadline_exceeded=time.monotonic() - queued_at > 0.5,
                    current_error_codes=error_codes,
                    evaluation_eligible=not bool(error_codes),
                    supported_fault_codes=list(
                        getattr(
                            predictor,
                            "supported_fault_codes",
                            [
                                c
                                for c in predictor.metadata.get("classes", [])
                                if c != "NO_ERROR"
                            ],
                        )
                    ),
                    mode="observation_only",
                )
                self._publish(generation, run_id, result, received_clock=queued_at)
            except Exception as error:
                buffer.clear()
                with self.lock:
                    self.counters["errors"] += 1
                self._publish(
                    generation,
                    run_id,
                    {
                        "status": "inference_error",
                        "reason": "prediction_failed",
                        "input_valid": False,
                        "probabilities": None,
                        "model_version": self.model_version,
                        "record_id": record.get("record_id"),
                        "reference_time": record.get("timestamp"),
                        "processed_at": datetime.now(UTC).isoformat(),
                    },
                    received_clock=queued_at,
                )
                logger.warning("ML prediction failed type=%s", type(error).__name__)
            finally:
                self.queue.task_done()
