"""개인용 읽기 전용 센서 모니터. .env·SDK 프로필·유료 API를 사용하지 않는다."""

import argparse
import getpass
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class StreamError(Exception):
    def __init__(self, status_code=None):
        self.status_code = status_code


class RevocationTimeoutError(Exception):
    pass


def verify_revocation(monitor, *, max_wait=20):
    """Revoke only this monitor's session; never accept a login error as a pass."""
    states = monitor.stream()
    try:
        first = next(states)
        monitor.logout()
        started = time.monotonic()
        discarded = 0
        while time.monotonic() - started < max_wait:
            try:
                next(states)
            except StreamError as error:
                elapsed = time.monotonic() - started
                if error.status_code != 401:
                    raise
                if elapsed >= max_wait:
                    raise RevocationTimeoutError() from None
                return {
                    "run_id": first["run_id"],
                    "status_code": 401,
                    "elapsed_seconds": elapsed,
                    "discarded_snapshots": discarded,
                }
            # The server revalidates every 10s. Do not display buffered states
            # after logout as if this session still had valid authorization.
            discarded += 1
        raise RevocationTimeoutError()
    finally:
        states.close()


def sse_events(response):
    """Parse bounded UTF-8 SSE frames without logging remote response bodies."""
    event = "message"
    data = []
    frame_bytes = 0
    first_line = True
    while True:
        raw = response.readline(65_537)
        if not raw:
            raise StreamError()
        frame_bytes += len(raw)
        if len(raw) > 65_536 or frame_bytes > 1_000_000:
            raise ValueError("SSE 응답 크기 초과")
        line = raw.decode("utf-8").rstrip("\r\n")
        if first_line:
            line = line.removeprefix("\ufeff")
            first_line = False
        if not line:
            if data:
                yield event, json.loads("\n".join(data))
            event, data, frame_bytes = "message", [], 0
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a login body or Bearer token to another location.
        return None


class Monitor:
    def __init__(self, base_url):
        parts = urlsplit(base_url)
        loopback = parts.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            parts.scheme not in {"http", "https"}
            or (parts.scheme == "http" and not loopback)
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("HTTPS 주소 또는 로컬 HTTP 주소만 사용할 수 있습니다.")
        self.base_url = base_url.rstrip("/")
        self.token = ""
        self.opener = build_opener(NoRedirect())

    def request(self, path, *, body=None, method=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self.base_url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        with self.opener.open(request, timeout=10) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("응답 크기 초과")
            return json.loads(raw) if raw else None

    def login(self, employee_no, password):
        response = self.request(
            "/auth/login", body={"employee_no": employee_no, "password": password}
        )
        self.token = response["access_token"]

    def stream(self):
        request = Request(
            self.base_url + "/telemetry/stream",
            headers={
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {self.token}",
            },
        )
        with self.opener.open(request, timeout=10) as response:
            content_type = response.headers.get("Content-Type", "")
            if content_type.partition(";")[0].strip().lower() != "text/event-stream":
                raise ValueError("SSE 응답 형식 오류")
            for event, payload in sse_events(response):
                if not isinstance(payload, dict):
                    raise ValueError("SSE 응답 형식 오류")
                if event == "error":
                    status_code = payload.get("status_code")
                    if type(status_code) is not int or not 400 <= status_code <= 599:
                        raise ValueError("SSE 오류 상태 형식 오류")
                    raise StreamError(status_code)
                if event != "snapshot":
                    continue
                if payload.get("event") != "snapshot" or not isinstance(
                    payload.get("state"), dict
                ):
                    raise ValueError("SSE 스냅샷 형식 오류")
                yield payload["state"]

    def logout(self):
        try:
            if self.token:
                self.request("/auth/logout", method="POST")
        finally:
            self.token = ""


def render(state):
    record = state.get("telemetry") or {}
    status = (
        "송신 연결 없음"
        if not state["producer_connected"]
        else "수신 지연·대기"
        if state["stale"]
        else "수신 중"
    )
    lines = [
        f"[{status}] 세션={state['run_id'] or '없음'} 순번={state['sequence']}",
        f"측정={record.get('timestamp', '없음')} 서버처리={state['received_at'] or '없음'}",
        f"DB={state['db_status']} AI={state['agent_status']} 문맥={state['context_preset']}",
    ]
    for field in (
        "rpm",
        "dc_input_current_a",
        "dc_bus_voltage_v",
        "motor_housing_temp_c",
        "de_vibration_rms_g",
        "de_kurtosis",
        "nde_vibration_rms_g",
        "nde_kurtosis",
        "infeed_present",
        "outfeed_present",
    ):
        value = record.get(field)
        lines.append(f"  {field}: {'결측/미수신' if value is None else value}")
    for incident in state["incidents"][-10:]:
        lines.append(
            f"  사건 {','.join(incident['codes'])} {incident['severity']} "
            f"{incident['status']} {incident['incident_id']}"
        )
    if state["stale"]:
        lines.append("마지막 값은 현재 정상 상태를 보장하지 않습니다.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://<EC2_IP>/api")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--stream", action="store_true", help="SSE 실시간 구독 검증")
    parser.add_argument(
        "--verify-revocation",
        action="store_true",
        help="검증용 로그인 세션을 로그아웃하고 기존 SSE의 401 종료 확인",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        help="SSE 스냅샷 N개를 받은 뒤 종료 (표본/ACK 건수 아님)",
    )
    args = parser.parse_args()
    if args.verify_revocation and (
        args.stream or args.once or args.max_events is not None
    ):
        parser.error("--verify-revocation은 다른 조회 모드 옵션과 함께 쓰지 않습니다.")
    if args.max_events is not None and (
        not args.stream or args.max_events < 1 or args.once
    ):
        parser.error(
            "--max-events는 --stream과 양수로 사용하며 --once와 함께 쓰지 않습니다."
        )
    monitor = None
    states = None
    try:
        if not sys.stdin.isatty():
            print(
                "본인 대화형 터미널에서 실행하세요. 비밀번호를 파일·파이프로 전달하지 마세요."
            )
            return 1
        monitor = Monitor(args.base_url)
        employee_no = input("로그인 사번: ").strip()
        password = getpass.getpass("로그인 비밀번호 (숨김): ")
        monitor.login(employee_no, password)
        del password
        print("읽기 전용 개인 모니터 · 종료 Ctrl+C · AI 분석을 요청하지 않습니다.")
        if args.verify_revocation:
            print(
                "SSE 첫 수신 후 이 도구의 로그인 세션만 로그아웃하고 401을 확인합니다."
            )
            result = verify_revocation(monitor)
            print(
                "RESULT: PASS_SSE_SESSION_REVOCATION · "
                f"HTTP {result['status_code']} · {result['elapsed_seconds']:.2f}초 · "
                f"로그아웃 후 스냅샷 {result['discarded_snapshots']}개는 표시하지 않음"
            )
            print(f"검증 세션: {result['run_id'] or '송신 세션 없음'}")
            return 0
        if args.stream:
            print("SSE 구독 · 연결 오류/인증 만료 시 중단 후 직접 재실행합니다.")
        previous = None
        previous_session = None
        count = 0
        states = monitor.stream() if args.stream else None
        while True:
            state = (
                next(states) if args.stream else monitor.request("/telemetry/latest")
            )
            count += 1
            session = (state["epoch"], state["run_id"])
            if (
                args.stream
                and previous_session is not None
                and session != previous_session
            ):
                print(
                    "새 프로세스/감지 세션 · 이전 세션 사건의 회복을 뜻하지 않습니다."
                )
            previous_session = session
            identity = (state["epoch"], state["sequence"], state["stale"])
            if identity != previous:
                if args.stream:
                    print(f"SSE snapshot #{count}")
                print(render(state), flush=True)
                previous = identity
            if args.once or (args.max_events is not None and count >= args.max_events):
                if args.stream:
                    print(
                        f"SSE 스냅샷 {count}개 수신 완료 (센서 표본/ACK 건수와 다름)."
                    )
                break
            if not args.stream:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n조회 종료")
    except HTTPError as error:
        print(
            f"조회 실패 HTTP {error.code}. 로그인·권한·조회 API 배포 여부를 확인하세요."
        )
        return 1
    except StreamError as error:
        if error.status_code in (401, 403):
            print(f"SSE 인증 종료 HTTP {error.status_code}. 다시 로그인해 실행하세요.")
        elif error.status_code is not None:
            print(f"SSE 서버 오류 HTTP {error.status_code}. 잠시 후 다시 실행하세요.")
        else:
            print("SSE 연결 종료. 이전 값을 정상으로 해석하지 말고 다시 실행하세요.")
        return 1
    except RevocationTimeoutError:
        print(
            "RESULT: FAIL_SSE_SESSION_REVOCATION · 20초 내 SSE 인증 종료를 확인하지 못함"
        )
        return 1
    except (URLError, OSError, ValueError, KeyError):
        print(
            "조회 실패. 연결·인증서·응답 형식을 확인하세요. 이전 값을 정상으로 해석하지 마세요."
        )
        return 1
    finally:
        if states is not None:
            states.close()
        if monitor:
            try:
                monitor.logout()
            except (URLError, OSError, ValueError):
                print("로그아웃 확인 실패. 로그인 세션은 서버의 만료 정책을 따릅니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
