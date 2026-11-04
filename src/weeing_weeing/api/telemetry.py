"""순차 센서 처리와 선택적 DB 작업 등록. LLM은 별도 실행기에서만 호출한다."""

import asyncio
import hashlib
import hmac
import logging
from datetime import UTC, datetime
from threading import Lock

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from weeing_weeing.api import telemetry_live
from weeing_weeing.api.simulator_context import COVERAGE, ENABLED, parse_simulator_frame
from weeing_weeing.config import get_settings
from weeing_weeing.contracts import IncidentStatus, Severity
from weeing_weeing.detector.interface import HistoryDetector
from weeing_weeing.ingest.interface import JsonTelemetryInput, TelemetryInputError

router = APIRouter(tags=["telemetry"])
# Uvicorn configures this logger's parent with a console handler at INFO.
logger = logging.getLogger("uvicorn.error.telemetry")
# One active producer per process. Use a single Uvicorn worker for this MVP.
_producer = Lock()
PRODUCER_IDLE_SECONDS = 15


def _simulation_rpm_allowed(websocket, settings):
    return (
        settings.telemetry_simulation_rpm_enabled
        and not settings.telemetry_auth_required
        and not settings.telemetry_producer_token_sha256.strip()
        and not settings.analysis_auto_enabled
        and websocket.client is not None
        and websocket.client.host in {"127.0.0.1", "::1"}
        and websocket.url.hostname in {"127.0.0.1", "localhost", "::1"}
    )


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
        self.analysis_service = None
        self.ml_service = None
        self.ml_errors = {}
        self.run_started_at = None
        self.history = HistoryDetector(
            output,
            enabled_codes=ENABLED if context_preset == "UNREAL_STATE" else None,
            source={
                "kind": "websocket",
                "input_path": "WebSocket -> JsonTelemetryInput -> HistoryDetector",
                "context_preset": context_preset,
                "assumptions": (
                    "UNREAL SIMULATOR: operating state and actor events; not a real PLC. "
                    "M04/M19 explicitly not evaluated."
                    if context_preset == "UNREAL_STATE"
                    else "SIM_RPM LOCAL TEST ONLY: fixed speed assumed; run start is "
                    "the first valid sample; not verified operational PLC context"
                    if context_preset == "SIM_RPM"
                    else "No operational context supplied"
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
        if self.context_preset == "UNREAL_STATE":
            if _plc_context is None:
                raise TelemetryInputError("Simulator context required")
            context = _plc_context
        if self.context_preset == "SIM_RPM":
            if self.run_started_at is None:
                self.run_started_at = record.timestamp
            context.update(
                run_started_at=self.run_started_at,
                fixed_speed=True,
                recipe_id="SIM_RPM_LOCAL_ONLY",
                config_version="SIM_RPM_V1",
            )
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
                "[Error 진입] run=%s codes=%s incident_id=%s agent=%s",
                self.history.run_path.name,
                ",".join(incident["codes"]),
                incident["incident_id"],
                "등록 시도"
                if self.analysis_service and self.analysis_service.analysis_enabled
                else "미연결(DB 저장 전용)"
                if self.analysis_service
                else "미연결",
            )
        analysis = (
            self.analysis_service.ingest(record, changes)
            if self.analysis_service
            else {"agent_status": "not_connected"}
        )
        response = {
            "status": "processed",
            "record_id": record.record_id,
            "timestamp": record.timestamp.isoformat(),
            "incidents": [item.model_dump(mode="json") for item in changes],
            "error_entries": entries,
            **analysis,
        }
        if self.context_preset == "UNREAL_STATE":
            response["rule_coverage"] = COVERAGE
        telemetry_live.live_state.publish(self.history.run_path.name, record, response)
        if self.ml_service:
            # 추론 실패는 Detector의 결과/응답을 바꾸지 않는다.
            try:
                for incident in changes:
                    self.ml_errors.pop(incident.incident_id, None)
                    if incident.severity == Severity.ERROR and incident.status not in (
                        IncidentStatus.RECOVERED,
                        IncidentStatus.CLOSED,
                    ):
                        self.ml_errors[incident.incident_id] = list(incident.codes)
                codes = sorted(
                    {code for values in self.ml_errors.values() for code in values}
                )
                self.ml_service.submit(
                    self.history.run_path.name, record.model_dump(mode="json"), codes
                )
            except Exception as error:
                logger.warning("ML dispatch failed type=%s", type(error).__name__)
        return response

    def receive(self, message):
        if self.context_preset == "UNREAL_STATE":
            wire, context = parse_simulator_frame(message)
            return self.receiver.receive(wire, context)
        return self.receiver.receive(message)

    def close(self):
        if self.failed:
            # process() already records failure. Never reuse or retry that instance.
            return
        self.history.close(reason="websocket_disconnect")


@router.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket, context: str = "NONE"):
    settings = get_settings()
    expected = settings.telemetry_producer_token_sha256.strip().lower()
    if settings.telemetry_auth_required or expected:
        authorization = getattr(websocket, "headers", {}).get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        configured = len(expected) == 64 and all(
            c in "0123456789abcdef" for c in expected
        )
        if not (
            configured
            and scheme.lower() == "bearer"
            and token
            and hmac.compare_digest(
                hashlib.sha256(token.encode()).hexdigest(), expected
            )
        ):
            # Deny before accept, producer lock and history allocation. No token echo.
            await websocket.close(code=1008)
            return
    await websocket.accept()
    if context not in {"NONE", "RUN_ONLY", "MINIMAL", "SIM_RPM", "UNREAL_STATE"}:
        await websocket.send_json({"status": "rejected", "code": "invalid_context"})
        await websocket.close(code=1008)
        return
    if context == "UNREAL_STATE" and not settings.telemetry_unreal_context_enabled:
        await websocket.send_json(
            {"status": "rejected", "code": "unreal_context_disabled"}
        )
        await websocket.close(code=1008)
        return
    if context == "SIM_RPM" and not _simulation_rpm_allowed(websocket, settings):
        await websocket.send_json(
            {"status": "rejected", "code": "simulation_context_disabled"}
        )
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
        session.analysis_service = getattr(
            getattr(getattr(websocket, "app", None), "state", None),
            "analysis_service",
            None,
        )
        session.ml_service = getattr(
            getattr(getattr(websocket, "app", None), "state", None), "ml_service", None
        )
        if session.ml_service:
            session.ml_service.begin(session.history.run_path.name)
        telemetry_live.live_state.start(session.history.run_path.name, context)
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
                "agent_status": "connected"
                if session.analysis_service
                and session.analysis_service.analysis_enabled
                else "not_connected",
            }
        )
        last_valid = asyncio.get_running_loop().time()
        while True:
            remaining = PRODUCER_IDLE_SECONDS - (
                asyncio.get_running_loop().time() - last_valid
            )
            try:
                frame = await asyncio.wait_for(
                    websocket.receive(), timeout=max(0, remaining)
                )
            except TimeoutError:
                await websocket.send_json({"status": "failed", "code": "producer_idle"})
                await websocket.close(code=1008)
                return
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
            if response.get("status") == "processed":
                last_valid = asyncio.get_running_loop().time()
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
            if session is not None:
                telemetry_live.live_state.end(session.history.run_path.name)
                if getattr(session, "ml_service", None):
                    session.ml_service.end(session.history.run_path.name)
            _producer.release()
