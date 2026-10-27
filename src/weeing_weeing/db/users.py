"""사용자 계정과 로그인 세션(app_user·user_session, #62).

- 비밀번호: 표준 라이브러리 scrypt(솔트 16바이트)로 해시해 저장한다. 원문은 저장하지 않는다.
- 세션: 로그인하면 임의 토큰(32바이트)을 돌려주고, DB에는 SHA-256만 둔다.
  로그아웃·비활성화·비밀번호 변경은 행을 지워 즉시 끊는다.
"""

import base64
import hashlib
import hmac
import secrets
import threading
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from weeing_weeing.contracts import Role, UserAccount
from weeing_weeing.db.models import SessionRow, UserRow
from weeing_weeing.db.session import Repository, now, utc

# OWASP 권장 하한(N=2^17, r=8, p=1). 로그인 한 번에 약 0.1초, 메모리 128MB.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**17, 8, 1
SCRYPT_MAXMEM = 256 * 1024 * 1024
MIN_PASSWORD_LENGTH = 8
# 해시 한 번에 128MB를 쓰므로 동시에 도는 개수를 묶는다. 로그인이 몰려도 메모리는 이 배수까지만.
_KDF_SLOTS = threading.BoundedSemaphore(4)


class DuplicateUserError(ValueError):
    """이미 있는 사번으로 계정을 만들려 했다."""


class UnknownUserError(LookupError):
    """없는 사번이다."""


class LastAdminError(ValueError):
    """마지막 활성 관리자의 관리자 권한을 빼거나 비활성화하려 했다(아무도 계정을 관리할 수 없게 됨)."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    with _KDF_SLOTS:
        return hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM
        )


def check_password_rules(password: str, employee_no: str | None = None) -> None:
    """길이, 공백만인 값, 사번과 같은 값을 막는다. 어기면 ValueError(이유 포함)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")
    if not password.strip():
        raise ValueError("비밀번호가 공백뿐입니다.")
    if employee_no is not None and password.casefold() == employee_no.casefold():
        raise ValueError("비밀번호를 사번과 같게 둘 수 없습니다.")


def hash_password(password: str) -> str:
    """`scrypt$N$r$p$솔트$해시` 형식. 매개변수를 함께 저장해 나중에 올려도 옛 해시를 검증한다."""
    check_password_rules(password)
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


# 없는 사번으로 로그인할 때도 같은 시간이 걸리게 해 사번 존재 여부가 드러나지 않게 한다.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _account(row: UserRow) -> UserAccount:
    return UserAccount(
        employee_no=row.employee_no,
        name=row.name,
        role=Role(row.role),
        is_admin=row.is_admin,
        is_active=row.is_active,
        created_at=utc(row.created_at),
        last_login_at=utc(row.last_login_at),
    )


class SqlUsers(Repository):
    # --- 계정 ---

    def create_user(self, account: UserAccount, password: str) -> UserAccount:
        check_password_rules(password, account.employee_no)
        stamp = now()
        row = UserRow(
            employee_no=account.employee_no,
            name=account.name,
            role=account.role.value,
            is_admin=account.is_admin,
            is_active=account.is_active,
            password_hash=hash_password(password),
            created_at=stamp,
            updated_at=stamp,
        )
        try:
            with self._transaction() as session:
                session.add(row)
        except IntegrityError as exc:
            raise DuplicateUserError(account.employee_no) from exc
        return _account(row)

    def get_user(self, employee_no: str) -> UserAccount | None:
        with self._transaction() as session:
            row = session.get(UserRow, employee_no)
            return None if row is None else _account(row)

    def list_users(self) -> list[UserAccount]:
        with self._transaction() as session:
            rows = session.scalars(select(UserRow).order_by(UserRow.employee_no))
            return [_account(row) for row in rows]

    def update_user(
        self,
        employee_no: str,
        *,
        name: str | None = None,
        role: Role | None = None,
        is_admin: bool | None = None,
        is_active: bool | None = None,
    ) -> UserAccount:
        """None인 칸은 그대로 둔다. 비활성화하면 그 사람의 세션을 모두 끊는다."""
        with self._transaction() as session:
            if is_admin is not None or is_active is not None:
                # 관리자 행을 먼저 잠근다. 두 관리자가 동시에 서로를 해제해도 차례로 처리돼
                # 마지막 관리자 검사가 맞게 돈다(PostgreSQL. SQLite는 쓰기 잠금으로 이미 차례).
                session.execute(
                    select(UserRow.employee_no)
                    .where(UserRow.is_admin.is_(True), UserRow.is_active.is_(True))
                    .with_for_update()
                )
            row = self._row(session, employee_no)
            was_admin = row.is_admin and row.is_active
            changes = {"name": name, "is_admin": is_admin, "is_active": is_active}
            if role is not None:
                changes["role"] = Role(role).value
            for field, value in changes.items():
                if value is not None:
                    setattr(row, field, value)
            # 이름·직책 검증은 계약 모델로 한 번 더(빈 이름 등)
            account = _account(row)
            if was_admin and not (row.is_admin and row.is_active):
                admins = session.scalars(
                    select(UserRow.employee_no).where(
                        UserRow.is_admin.is_(True), UserRow.is_active.is_(True)
                    )
                ).all()
                if not admins:  # autoflush로 이 행의 변경이 이미 반영된 상태
                    raise LastAdminError(employee_no)
            row.updated_at = now()
            if not row.is_active:
                session.execute(
                    delete(SessionRow).where(SessionRow.employee_no == employee_no)
                )
            return account

    def set_password(self, employee_no: str, password: str) -> None:
        """비밀번호를 바꾸고 기존 세션을 모두 끊는다."""
        check_password_rules(password, employee_no)
        password_hash = hash_password(password)
        with self._transaction() as session:
            row = self._row(session, employee_no)
            row.password_hash = password_hash
            row.updated_at = now()
            session.execute(
                delete(SessionRow).where(SessionRow.employee_no == employee_no)
            )

    # --- 로그인 ---

    def check_password(self, employee_no: str, password: str) -> bool:
        """세션을 만들지 않고 비밀번호만 확인한다(본인 비밀번호 변경 전 확인 등)."""
        with self._transaction() as session:
            row = session.get(UserRow, employee_no)
        if row is None:
            verify_password(password, _DUMMY_HASH)
            return False
        return verify_password(password, row.password_hash)

    def login(
        self, employee_no: str, password: str, *, ttl: timedelta
    ) -> tuple[str, datetime, UserAccount] | None:
        """맞으면 (토큰, 만료 시각, 계정). 사번·비밀번호가 틀리거나 비활성 계정이면 None."""
        with self._transaction() as session:
            row = session.get(UserRow, employee_no)
        if row is None:
            verify_password(password, _DUMMY_HASH)
            return None
        if not verify_password(password, row.password_hash) or not row.is_active:
            return None

        token = secrets.token_urlsafe(32)
        stamp = now()
        expires_at = stamp + ttl
        with self._transaction() as session:
            row = session.get(UserRow, employee_no)
            if row is None or not row.is_active:  # 확인하는 사이에 지워졌거나 막힘
                return None
            row.last_login_at = stamp
            # 만료된 세션은 로그인할 때 함께 정리한다(따로 청소 작업을 두지 않는다).
            session.execute(
                delete(SessionRow).where(
                    SessionRow.employee_no == employee_no,
                    SessionRow.expires_at <= stamp,
                )
            )
            session.add(
                SessionRow(
                    token_hash=_token_hash(token),
                    employee_no=employee_no,
                    created_at=stamp,
                    expires_at=expires_at,
                )
            )
            return token, expires_at, _account(row)

    def user_for_token(self, token: str) -> UserAccount | None:
        """유효한 세션의 계정. 없거나 만료됐거나 비활성 계정이면 None."""
        if not token.isascii():  # 발급 토큰은 URL-safe ASCII뿐이다
            return None
        query = (
            select(UserRow)
            .join(SessionRow, SessionRow.employee_no == UserRow.employee_no)
            .where(
                SessionRow.token_hash == _token_hash(token),
                SessionRow.expires_at > now(),
                UserRow.is_active.is_(True),
            )
        )
        with self._transaction() as session:
            row = session.scalars(query).first()
            return None if row is None else _account(row)

    def logout(self, token: str) -> None:
        with self._transaction() as session:
            session.execute(
                delete(SessionRow).where(SessionRow.token_hash == _token_hash(token))
            )

    @staticmethod
    def _row(session, employee_no: str) -> UserRow:
        row = session.get(UserRow, employee_no)
        if row is None:
            raise UnknownUserError(employee_no)
        return row
