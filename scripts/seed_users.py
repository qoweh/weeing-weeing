"""시연용 계정을 DB에 만든다(#62). 이미 있는 사번은 건드리지 않는다.

입력: data/seed/demo_users_v1.toml, .env(DATABASE_URL)
비밀번호: 기본은 계정마다 임의로 만들어, 만든 즉시 **한 번만** 화면에 출력한다.
--ask-password면 모든 계정에 쓸 값을 입력받는다(명령줄·셸 기록에 남지 않게).
종료 코드: 0 성공 / 2 DB 연결 실패·비밀번호 규칙 위반

    make seed-users                       # 임의 비밀번호(출력된 값을 보관)
    make seed-users ARGS=--ask-password   # 모든 시연 계정을 같은 비밀번호로
"""

import argparse
import getpass
import secrets
import sys
import tomllib
from pathlib import Path

from weeing_weeing.config import PROJECT_ROOT, get_settings
from weeing_weeing.contracts import UserAccount
from weeing_weeing.db import interface as db

SEED = PROJECT_ROOT / "data/seed/demo_users_v1.toml"


def load(path: Path) -> list[UserAccount]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return [UserAccount(**user) for user in raw.get("users", [])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ask-password",
        action="store_true",
        help="모든 계정에 쓸 비밀번호를 입력받음(8자 이상)",
    )
    parser.add_argument("--file", type=Path, default=SEED)
    args = parser.parse_args(argv)
    shared = getpass.getpass("시연 계정 비밀번호: ") if args.ask_password else None

    settings = get_settings()
    created = 0
    try:
        repo = db.open_users(settings.database_url, timeout_s=settings.db_timeout_s)
        for account in load(args.file):
            if repo.get_user(account.employee_no) is not None:
                print(f"[있음] {account.employee_no} {account.name}")
                continue
            password = shared or secrets.token_urlsafe(9)
            repo.create_user(account, password)
            created += 1
            # 만든 즉시 출력한다. 도중에 실패해도 이미 만든 계정의 비밀번호는 남는다.
            admin = " (관리자)" if account.is_admin else ""
            shown = "(입력한 값)" if shared else password
            print(
                f"[생성] {account.employee_no} {account.role.value}{admin}  비밀번호: {shown}"
            )
    except db.DatabaseUnavailableError as exc:
        print(f"DB 연결 실패: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:  # 비밀번호 규칙
        print(f"비밀번호 오류: {exc}", file=sys.stderr)
        return 2

    if created and not shared:
        print(
            "임의 비밀번호는 다시 볼 수 없다. 잊으면 관리자가 PUT /users/{사번}/password로 재설정"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
