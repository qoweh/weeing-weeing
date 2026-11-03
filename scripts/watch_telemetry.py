"""개인용 읽기 전용 센서 모니터. .env·SDK 프로필·유료 API를 사용하지 않는다."""

import argparse
import getpass
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


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
    args = parser.parse_args()
    monitor = None
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
        previous = None
        while True:
            state = monitor.request("/telemetry/latest")
            identity = (state["epoch"], state["sequence"], state["stale"])
            if identity != previous:
                print(render(state), flush=True)
                previous = identity
            if args.once:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n조회 종료")
    except HTTPError as error:
        print(
            f"조회 실패 HTTP {error.code}. 로그인·권한·조회 API 배포 여부를 확인하세요."
        )
        return 1
    except (URLError, OSError, ValueError, KeyError):
        print(
            "조회 실패. 연결·인증서·응답 형식을 확인하세요. 이전 값을 정상으로 해석하지 마세요."
        )
        return 1
    finally:
        if monitor:
            try:
                monitor.logout()
            except (URLError, OSError, ValueError):
                print("로그아웃 확인 실패. 로그인 세션은 서버의 만료 정책을 따릅니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
