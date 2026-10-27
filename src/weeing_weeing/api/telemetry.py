"""Sequential telemetry WebSocket. No LLM calls or PLC control live here."""

import asyncio
import logging
from datetime import UTC, datetime
from threading import Lock

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from weeing_weeing.config import get_settings
from weeing_weeing.contracts import IncidentStatus, Severity
from weeing_weeing.detector.interface import HistoryDetector
from weeing_weeing.ingest.interface import JsonTelemetryInput, TelemetryInputError

router = APIRouter(tags=["telemetry"])
# Uvicorn configures this logger's parent with a console handler at INFO.
logger = logging.getLogger("uvicorn.error.telemetry")
# One active producer per process. Use a single Uvicorn worker for this MVP.
_producer = Lock()


async def _finish_worker(task):
    """Wait through cancellation without retrying the synchronous operation.

    A plain asyncio Task.cancel() can cancel the awaiting route while its thread
    keeps writing. Cleanup must wait for that thread, even on repeated cancels.
    """
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


class TelemetrySession:
    def __init__(self, output, context_preset):
        self.context_preset = context_preset
        self.first = True
        self.asset = None
        self.error_ids = set()
        self.failed = False
        self.processed_count = 0
        self.history = HistoryDetector(
            output,
            source={
                "kind": "websocket",
                "input_path": "WebSocket -> JsonTelemetryInput -> HistoryDetector",
                "context_preset": context_preset,
                "assumptions": (
                    "No operational context supplied"
                    if context_preset == "NONE"
                    else "SIMULATION ONLY; not verified operational PLC context"
                ),
            },
        )
        self.receiver = JsonTelemetryInput(self._handle)

    def _handle(self, record, _plc_context):
        asset = (record.process_id, record.asset_id)
        if self.asset is not None and asset != self.asset:
            raise TelemetryInputError("One process/asset per connection")
        context = {} if self.context_preset == "NONE" else {"run_cmd": True}
        if self.context_preset == "MINIMAL":
            context.update(
                events_reliable=True,
                downstream_ready=True,
                tracking_reset=(
                    self.first
                    and not record.infeed_present
                    and not record.outfeed_present
                ),
            )
        try:
            changes = self.history.process(record, context)
        except Exception:
            self.failed = True
            raise
        self.first = False
        self.asset = asset
        entries = []
        for incident in changes:
            if (
                incident.severity == Severity.ERROR
                and incident.status
                not in (IncidentStatus.RECOVERED, IncidentStatus.CLOSED)
                and incident.incident_id not in self.error_ids
            ):
                entries.append(incident.model_dump(mode="json"))
                self.error_ids.add(incident.incident_id)
        self.processed_count += 1
        logger.info(
            "[센서 처리 #%04d] run=%s processed_at=%s data=%s",
            self.processed_count,
            self.history.run_path.name,
            datetime.now(UTC).isoformat(timespec="milliseconds"),
            record.model_dump_json(),
        )
        for incident in entries:
            logger.info(
                "[Error 진입] run=%s codes=%s incident_id=%s (Agent 미연결)",
                self.history.run_path.name,
                ",".join(incident["codes"]),
                incident["incident_id"],
            )
        return {
            "status": "processed",
            "record_id": record.record_id,
            "timestamp": record.timestamp.isoformat(),
            "incidents": [item.model_dump(mode="json") for item in changes],
            "error_entries": entries,
            "agent_status": "not_connected",
        }

    def receive(self, message):
        return self.receiver.receive(message)

    def close(self):
        if self.failed:
            # process() already records failure. Never reuse or retry that instance.
            return
        self.history.close(reason="websocket_disconnect")


@router.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket, context: str = "NONE"):
    await websocket.accept()
    if context not in {"NONE", "RUN_ONLY", "MINIMAL"}:
        await websocket.send_json({"status": "rejected", "code": "invalid_context"})
        await websocket.close(code=1008)
        return
    if not _producer.acquire(blocking=False):
        await websocket.send_json({"status": "rejected", "code": "producer_busy"})
        await websocket.close(code=1013)
        return
    session = None
    pending = None

    async def run_worker(operation, *args):
        nonlocal pending
        pending = asyncio.create_task(anyio.to_thread.run_sync(operation, *args))
        try:
            result = await asyncio.shield(pending)
        except asyncio.CancelledError:
            # Retain the task: construction may finish after this cancellation,
            # and receive may still be writing. The finally block drains it.
            raise
        except BaseException:
            pending = None
            raise
        else:
            pending = None
            return result

    try:
        session = await run_worker(
            TelemetrySession, get_settings().telemetry_history_dir, context
        )
        logger.info(
            "[센서 연결] run=%s context=%s",
            session.history.run_path.name,
            context,
        )
        await websocket.send_json(
            {
                "status": "connected",
                "run_id": session.history.run_path.name,
                "run_path": str(session.history.run_path.resolve()),
                "context_preset": context,
                "agent_status": "not_connected",
            }
        )
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                break
            message = frame.get("text")
            if message is None:
                message = frame.get("bytes", b"")
            try:
                response = await run_worker(session.receive, message)
            except TelemetryInputError:
                # Never echo an unvalidated ID, payload, or exception details.
                logger.warning("[센서 거부] code=invalid_telemetry")
                response = {"status": "rejected", "code": "invalid_telemetry"}
            except Exception as error:
                logger.error("Telemetry processing failed: %s", type(error).__name__)
                await websocket.send_json(
                    {"status": "failed", "code": "processing_failed"}
                )
                await websocket.close(code=1011)
                return
            await websocket.send_json(response)
    except (WebSocketDisconnect, OSError):
        # A missing response doesn't prove that the last input wasn't persisted.
        pass
    except Exception as error:
        logger.error("Telemetry session failed: %s", type(error).__name__)
        await websocket.send_json({"status": "failed", "code": "session_failed"})
        await websocket.close(code=1011)
    finally:
        try:
            with anyio.CancelScope(shield=True):
                if pending is not None:
                    try:
                        result = await _finish_worker(pending)
                        if session is None:
                            # Cancellation during creation must not orphan the
                            # newly created history instance.
                            session = result
                    except Exception as error:
                        logger.error(
                            "Telemetry pending operation failed: %s",
                            type(error).__name__,
                        )
                if session is not None:
                    closing = asyncio.create_task(
                        anyio.to_thread.run_sync(session.close)
                    )
                    await _finish_worker(closing)
                    logger.info(
                        "[센서 연결 종료] run=%s processed_messages=%d failed=%s",
                        session.history.run_path.name,
                        session.processed_count,
                        session.failed,
                    )
        except Exception as error:
            logger.error("Telemetry finalization failed: %s", type(error).__name__)
        finally:
            _producer.release()
