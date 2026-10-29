"""Send CSV rows over a real WebSocket, waiting for one ACK per row."""

import argparse
import json
import math
import sys
from itertools import chain
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websockets.exceptions import WebSocketException  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

from weeing_weeing.ingest.interface import CsvJsonSource, replay_json  # noqa: E402


def send_csv(csv_path, url, *, context="NONE", interval=0.5, timeout=10.0):
    replay_json((), lambda _: None, interval_s=interval)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    parts = urlsplit(url)
    if parts.scheme not in ("ws", "wss") or not parts.hostname:
        raise ValueError("Expected ws:// or wss:// server URL")
    if context not in {"NONE", "RUN_ONLY", "MINIMAL"}:
        raise ValueError("Unknown context preset")
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "context"]
    query.append(("context", context))
    address = urlunsplit(parts._replace(query=urlencode(query)))
    source = iter(CsvJsonSource(csv_path))
    # Validate the header and first row before connecting/creating a server run.
    first = next(source, None)
    if first is None:
        raise ValueError("CSV contains no telemetry rows")
    with connect(
        address,
        open_timeout=timeout,
        close_timeout=timeout,
        ping_interval=20,
        ping_timeout=timeout,
        max_size=1024 * 1024,
        max_queue=4,
    ) as websocket:
        ready = json.loads(websocket.recv(timeout=timeout))
        if ready.get("status") != "connected":
            raise RuntimeError("Server rejected the connection")
        print(f"[연결] context={context} | run={ready['run_path']}", flush=True)
        if context != "NONE":
            print("[주의] 선택한 운전 문맥은 시뮬레이션 가정입니다.", flush=True)
        count = 0
        seen = {}
        seen_jobs = {}

        def send(message):
            nonlocal count
            row = json.loads(message)
            websocket.send(message)
            response = json.loads(websocket.recv(timeout=timeout))
            if response.get("status") != "processed":
                raise RuntimeError(
                    "Server rejected or failed to process a row; replay stopped"
                )
            if response.get("record_id") != row["record_id"]:
                raise RuntimeError("Server ACK record_id mismatch")
            count += 1
            print(
                f"[처리 #{count:04d}] id={row['record_id']} "
                f"sensor_time={row['timestamp']} rpm={row['rpm']} "
                f"temp={row['motor_housing_temp_c']} "
                f"in={row['infeed_present']} out={row['outfeed_present']}",
                flush=True,
            )
            for incident in response["incidents"]:
                state = (incident["severity"], incident["status"])
                if seen.get(incident["incident_id"]) != state:
                    print(
                        f"  [사건] {','.join(incident['codes'])} "
                        f"{state[0]} {state[1]} id={incident['incident_id']}",
                        flush=True,
                    )
                    seen[incident["incident_id"]] = state
            for incident in response["error_entries"]:
                print(
                    f"  [Error 진입] {','.join(incident['codes'])} "
                    f"분석 대상 확인 (Agent {response.get('agent_status', 'not_connected')})",
                    flush=True,
                )
            if response.get("db_status") == "failed":
                raise RuntimeError(
                    "DB 저장 실패: 탐지 이력은 로컬에 남지만 DB에는 저장되지 않았습니다. 자동 재전송하지 않습니다"
                )
            for job in response.get("analysis_jobs", []):
                if seen_jobs.get(job["job_id"]) == job["status"]:
                    continue
                seen_jobs[job["job_id"]] = job["status"]
                print(
                    f"  [분석 작업] incident={job['incident_id']} job={job['job_id']} state={job['status']}",
                    flush=True,
                )

        replay_json(chain((first,), source), send, interval_s=interval)
    print(
        f"[송신 완료] {count}행 처리 응답 확인. 원본 ID·timestamp·센서값 유지.",
        flush=True,
    )
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "data/telemetry/battery_tray_transfer_5min_warning_error_v4.csv",
    )
    parser.add_argument("--url", default="ws://localhost:8000/ws/telemetry")
    parser.add_argument(
        "--context", choices=("NONE", "RUN_ONLY", "MINIMAL"), default="NONE"
    )
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    try:
        send_csv(
            args.csv,
            args.url,
            context=args.context,
            interval=args.interval,
            timeout=args.timeout,
        )
    except KeyboardInterrupt:
        print("[중단] 재접속·자동 재전송하지 않습니다.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, WebSocketException) as error:
        print(
            f"[실패] {type(error).__name__}: 송신 중단. 서버 상태·CSV를 확인하세요. 자동 재전송 없음.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
