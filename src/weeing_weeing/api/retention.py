"""Optional bounded background telemetry retention worker."""

import logging
from datetime import UTC, datetime
from threading import Event, Thread

from weeing_weeing.db.interface import open_engine
from weeing_weeing.db.retention import TelemetryRetention

logger = logging.getLogger("uvicorn.error.retention")


class RetentionWorker:
    def __init__(self, url: str, timeout: float):
        self.url, self.timeout = url, timeout
        self.stop_event = Event()
        self.thread = Thread(target=self.run, name="telemetry-retention", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=10)

    def run(self):
        engine = None
        cursor = 0
        delay = 15.0
        try:
            while not self.stop_event.wait(delay):
                try:
                    if engine is None:
                        engine = open_engine(self.url, timeout_s=self.timeout)
                    count, cursor = TelemetryRetention(engine).clean_batch(
                        datetime.now(UTC), cursor
                    )
                    delay = 0.5 if cursor else 15.0
                    if count:
                        logger.info("Expired telemetry removed: %d", count)
                except Exception:
                    logger.exception("Telemetry cleanup failed; will retry")
                    delay = 15.0
        finally:
            if engine is not None:
                engine.dispose()
