"""AWS 실시간 ML 결과 모니터. 웹 계정으로 로그인하며 .env/LLM을 사용하지 않는다."""

import argparse
import getpass
import sys
import time
from urllib.error import HTTPError, URLError

from watch_telemetry import Monitor


def render(state):
    prediction = state["prediction"]
    lines = [
        f"모델={state['model_version']} 세션={state['run_id']}",
        f"상태={prediction['status']} 사용가능={state['prediction_usable']} 지연={state['stale']}",
        f"기준시각={prediction.get('reference_time')} 추론={prediction.get('inference_ms')}ms",
    ]
    if state["prediction_usable"]:
        lines.append(f"향후 60초 Error 예측 확률={prediction['error_probability']:.2%}")
        lines.extend(
            f"  {item['code']}: {item['confidence']:.2%}"
            for item in prediction["fault_top3"]
        )
    else:
        lines.append(
            f"현재 예측 사용 불가: {prediction.get('reason', '수신 상태 확인')}"
        )
    if prediction.get("current_error_codes"):
        lines.append("현재 이미 Error: " + ", ".join(prediction["current_error_codes"]))
    lines.append(f"처리 통계={state['counters']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://<EC2_IP>/api")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    monitor = Monitor(args.base_url)
    print("로그인 정보는 터미널에서만 입력하세요. 모델은 4개 고장 코드만 학습했습니다.")
    try:
        employee = input("사번: ").strip()
        password = getpass.getpass("비밀번호: ")
        monitor.login(employee, password)
        del password
        previous = None
        while True:
            state = monitor.request("/ml/prediction")
            prediction = state["prediction"]
            key = (
                state["run_id"],
                state["stale"],
                prediction.get("record_id"),
                prediction["status"],
            )
            if key != previous:
                print(render(state), flush=True)
                previous = key
            if args.once:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    except HTTPError as error:
        print(
            f"조회 실패 HTTP {error.code}. 로그인/배포 상태를 확인하세요.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, KeyError, URLError, OSError):
        print("조회 실패. 연결 또는 응답 형식을 확인하세요.", file=sys.stderr)
        return 1
    finally:
        try:
            monitor.logout()
        except (HTTPError, URLError, OSError):
            print(
                "모니터 세션 로그아웃 실패. 세션 만료까지 재사용하지 마세요.",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
