"""#104 실제 WebSocket·Detector·SQLite·작업 실행 흐름 시연. Claude API 호출·비용 없음.

    PYTHONPATH=src uv run --no-sync python scripts/demo_auto_analysis.py

실제 Uvicorn을 임의 loopback 포트에 띄우고 CSV를 송신한다. 사용자 DB·8000 서버는 쓰지 않는다.
분석기는 지연 후 INSUFFICIENT_EVIDENCE를 반환하는 가짜이며 실제 RAG 품질 시험이 아니다.
"""

import argparse
import logging
import socket
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from uuid import uuid4

import uvicorn
from fastapi import FastAPI
from send_csv_websocket import send_csv

from weeing_weeing.api.analysis import AnalysisService
from weeing_weeing.api.telemetry import router
from weeing_weeing.config import PROJECT_ROOT
from weeing_weeing.contracts import AnalysisResult
from weeing_weeing.db.interface import open_analysis_jobs


class DemoAnalyzer:
    def __init__(self, delay):
        self.delay = delay

    def analyze(self, incident):
        time.sleep(self.delay)
        return AnalysisResult(
            incident_id=incident.incident_id,
            status="INSUFFICIENT_EVIDENCE",
            observed_facts="시연용 가짜 분석입니다. 실제 RAG·Claude를 호출하지 않았습니다.",
            limitations="자동 실행·저장 흐름만 검증. 실제 원인 판단에 사용할 수 없습니다.",
            model="demo/no-api",
            generated_at=datetime.now(UTC),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=PROJECT_ROOT
        / "data/telemetry/battery_tray_transfer_5min_warning_error_v4.csv",
    )
    parser.add_argument("--interval", type=float, default=0.02)
    parser.add_argument("--analysis-delay", type=float, default=2)
    args = parser.parse_args()
    if args.interval < 0 or not 0 <= args.analysis_delay <= 10:
        parser.error("interval은 0 이상, analysis-delay는 0~10초여야 합니다")
    output = PROJECT_ROOT / "outputs/analysis_demo" / uuid4().hex
    output.mkdir(parents=True)
    repo = open_analysis_jobs(f"sqlite:///{output / 'demo.db'}")
    service = AnalysisService(lambda: repo, lambda: DemoAnalyzer(args.analysis_delay))

    @asynccontextmanager
    async def lifespan(app):
        app.state.analysis_service = service
        service.start()
        try:
            yield
        finally:
            service.stop()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    # TelemetrySession의 실행 이력도 사용자 경로와 분리한다.
    import os

    previous = os.environ.get("TELEMETRY_HISTORY_DIR")
    os.environ["TELEMETRY_HISTORY_DIR"] = str(output / "history")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="info", lifespan="on"))
    thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    print(
        f"[시연 시작] Claude 비용 없음 / 임시 포트={port} / 결과={output}", flush=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("시연 서버 시작 실패")
            time.sleep(0.02)
        count = send_csv(
            args.csv,
            f"ws://127.0.0.1:{port}/ws/telemetry",
            context="MINIMAL",
            interval=args.interval,
            timeout=10,
        )
        deadline = time.monotonic() + 30
        while True:
            incidents = repo.list_incidents()
            jobs = [repo.latest_job(i.incident_id) for i in incidents]
            jobs = [j for j in jobs if j]
            if all(j["status"] not in ("PENDING", "RUNNING") for j in jobs):
                break
            if time.monotonic() > deadline:
                raise RuntimeError("시연 분석 완료 대기 초과")
            time.sleep(0.05)
        print(
            f"[시연 결과] 입력={count} 사건={len(incidents)} 분석작업={len(jobs)}",
            flush=True,
        )
        for job in jobs:
            result = repo.latest_analysis(job["incident_id"])
            print(
                f"  incident={job['incident_id']} state={job['status']} result={result.status if result else '-'}",
                flush=True,
            )
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        if previous is None:
            os.environ.pop("TELEMETRY_HISTORY_DIR", None)
        else:
            os.environ["TELEMETRY_HISTORY_DIR"] = previous
        if not thread.is_alive():
            repo._engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
