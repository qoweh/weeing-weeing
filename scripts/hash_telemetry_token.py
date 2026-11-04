"""사용자 터미널에서만 실행. 원본 토큰은 출력·저장하지 않고 SHA-256만 표시한다."""

import getpass
import hashlib
import sys


def main():
    if not sys.stdin.isatty():
        print(
            "본인 대화형 터미널에서 실행하세요. 토큰을 파일·파이프로 전달하지 마세요."
        )
        return 1
    token = getpass.getpass("송신 전용 토큰 (숨김, 32자 이상): ")
    confirm = getpass.getpass("송신 전용 토큰 확인 (숨김): ")
    if len(token) < 32 or token != confirm or any(c.isspace() for c in token):
        print("32자 이상 공백 없는 동일한 토큰을 입력해야 합니다.")
        return 1
    print(
        "TELEMETRY_PRODUCER_TOKEN_SHA256=" + hashlib.sha256(token.encode()).hexdigest()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
