"""단일 프로세스의 제한된 최신 상태. 구독자가 수신·저장을 지연시키지 않는다."""

import asyncio
import json
import time
from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

import anyio
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from weeing_weeing.api.auth import Credentials, CurrentUser, Users, current_user

router = APIRouter(tags=["telemetry"])


class LiveTelemetry:
    def __init__(self):
        self.lock = Lock()
        self.epoch = str(uuid4())
        self.sequence = 0
        self.run_id = None
        self.connected = False
        self.context = "NONE"
        self.received_at = None
        self.received_clock = None
        self.record = None
        self.incidents = {}
        self.db_status = "not_connected"
        self.agent_status = "not_connected"
        self.rule_coverage = None

    def start(self, run_id, context):
        with self.lock:
            self.run_id = run_id
            self.context = context
            self.connected = True
            self.record = self.received_at = self.received_clock = None
            self.incidents = {}
            self.db_status = self.agent_status = "not_connected"
            self.rule_coverage = None
            self.sequence += 1

    def publish(self, run_id, record, response):
        with self.lock:
            if run_id != self.run_id:
                return
            self.record = record.model_dump(mode="json")
            self.received_at = datetime.now(UTC).isoformat()
            self.received_clock = time.monotonic()
            self.db_status = response.get("db_status", "not_connected")
            self.agent_status = response.get("agent_status", "not_connected")
            self.rule_coverage = response.get("rule_coverage")
            for incident in response["incidents"]:
                self.incidents.pop(incident["incident_id"], None)
                self.incidents[incident["incident_id"]] = {
                    key: incident[key]
                    for key in (
                        "incident_id",
                        "codes",
                        "asset_id",
                        "first_detected_at",
                        "severity",
                        "status",
                    )
                }
            # UI cache only; authoritative incident history remains in the DB.
            while len(self.incidents) > 100:
                self.incidents.pop(next(iter(self.incidents)))
            self.sequence += 1

    def end(self, run_id):
        with self.lock:
            if self.run_id == run_id:
                self.connected = False
                self.sequence += 1

    def snapshot(self):
        with self.lock:
            age = (
                None
                if self.received_clock is None
                else max(0, time.monotonic() - self.received_clock)
            )
            return deepcopy(
                {
                    "epoch": self.epoch,
                    "sequence": self.sequence,
                    "run_id": self.run_id,
                    "producer_connected": self.connected,
                    "stale": age is None or age > 3 or not self.connected,
                    "age_seconds": age,
                    "received_at": self.received_at,
                    "context_preset": self.context,
                    "telemetry": self.record,
                    "incidents": list(self.incidents.values()),
                    "db_status": self.db_status,
                    "agent_status": self.agent_status,
                    "rule_coverage": self.rule_coverage,
                }
            )


live_state = LiveTelemetry()


@router.get("/telemetry/latest")
def latest_telemetry(user: CurrentUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return live_state.snapshot()


async def telemetry_events(authorize, *, interval=0.5, auth_interval=10):
    # Each subscriber reads a single bounded snapshot; no unbounded event queue.
    # Revalidate sessions every 10s, including logout, expiry and disabled users.
    checked = 0
    while True:
        if time.monotonic() >= checked:
            try:
                await anyio.to_thread.run_sync(authorize)
            except HTTPException as error:
                yield (
                    "event: error\ndata: "
                    + json.dumps(
                        {
                            "event": "error",
                            "status_code": error.status_code,
                            "message": "실시간 조회 인증을 다시 확인해 주세요.",
                        }
                    )
                    + "\n\n"
                )
                return
            checked = time.monotonic() + auth_interval
        yield (
            "event: snapshot\ndata: "
            + json.dumps(
                {
                    "event": "snapshot",
                    "state": live_state.snapshot(),
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
        await asyncio.sleep(interval)


@router.get("/telemetry/stream")
def stream_telemetry(user: CurrentUser, repo: Users, credentials: Credentials):
    return StreamingResponse(
        telemetry_events(lambda: current_user(repo, credentials)),
        media_type="text/event-stream",
        # Compression proxies can buffer SSE until a compressed block fills.
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
