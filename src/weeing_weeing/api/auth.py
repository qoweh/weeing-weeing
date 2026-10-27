"""로그인과 계정 관리 API(#62). 다른 라우터는 아래 의존성으로 권한을 건다.

    from weeing_weeing.api.auth import current_user, require_admin, require_roles

    @router.post("/reports/{id}/approve", dependencies=[Depends(require_roles(Role.MAINT_LEAD))])

인증은 `Authorization: Bearer <토큰>`. 토큰은 POST /auth/login이 주고, DB 세션 행으로 확인한다.
기존 엔드포인트(문서 업로드·센서 WebSocket)에는 아직 걸지 않았다(docs/AUTH.md).
"""

import logging
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from weeing_weeing.config import get_settings
from weeing_weeing.contracts import Role, UserAccount
from weeing_weeing.contracts.user import EMPLOYEE_NO_PATTERN
from weeing_weeing.db import interface as db

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False, description="POST /auth/login이 준 토큰")

PasswordField = Field(min_length=db.MIN_PASSWORD_LENGTH, max_length=256)


def users() -> db.UserRepository:
    try:
        return db.get_users()
    except db.DatabaseUnavailableError as exc:
        raise _db_unavailable(exc) from exc


def _db_unavailable(exc: Exception) -> HTTPException:
    logger.error("DB 연결 실패: %s", type(exc).__name__)
    return HTTPException(
        status_code=503,
        detail="사용자 DB에 연결하지 못했습니다. 잠시 후 다시 시도하세요.",
    )


def _bad_password(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


Users = Annotated[db.UserRepository, Depends(users)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


# --- 권한 의존성 (다른 라우터에서 쓴다) ---


def current_user(repo: Users, credentials: Credentials) -> UserAccount:
    """로그인한 사용자. 토큰이 없거나 만료·폐기됐거나 비활성 계정이면 401."""
    if credentials is None:
        raise _unauthorized("로그인이 필요합니다.")
    try:
        user = repo.user_for_token(credentials.credentials)
    except db.DatabaseUnavailableError as exc:
        raise _db_unavailable(exc) from exc
    if user is None:
        raise _unauthorized("로그인이 만료됐거나 유효하지 않습니다. 다시 로그인하세요.")
    return user


CurrentUser = Annotated[UserAccount, Depends(current_user)]


def require_admin(user: CurrentUser) -> UserAccount:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="관리자만 할 수 있습니다.")
    return user


def require_roles(*roles: Role):
    """지정한 직책 중 하나여야 통과(403). 관리자라도 직책이 다르면 막는다(업무 권한과 분리)."""
    allowed = frozenset(roles)

    def check(user: CurrentUser) -> UserAccount:
        if user.role not in allowed:
            names = ", ".join(sorted(r.value for r in allowed))
            raise HTTPException(status_code=403, detail=f"{names}만 할 수 있습니다.")
        return user

    return check


Admin = Annotated[UserAccount, Depends(require_admin)]


# --- 요청·응답 ---


class LoginRequest(BaseModel):
    employee_no: str = Field(max_length=32)
    password: str = Field(max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (OAuth2 토큰 종류 이름, 비밀 값 아님)
    expires_at: datetime
    user: UserAccount


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = PasswordField


class PasswordReset(BaseModel):
    password: str = PasswordField


class UserCreate(BaseModel):
    employee_no: str = Field(pattern=EMPLOYEE_NO_PATTERN)
    name: str = Field(min_length=1, max_length=64)
    role: Role
    is_admin: bool = False
    password: str = PasswordField


class UserUpdate(BaseModel):
    """보낸 칸만 바꾼다."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    role: Role | None = None
    is_admin: bool | None = None
    is_active: bool | None = None


# --- 로그인 ---


@router.post("/auth/login")
def login(body: LoginRequest, repo: Users) -> LoginResponse:
    ttl = timedelta(hours=get_settings().auth_session_hours)
    try:
        result = repo.login(body.employee_no, body.password, ttl=ttl)
    except db.DatabaseUnavailableError as exc:
        raise _db_unavailable(exc) from exc
    if result is None:
        # 사번이 없는지, 비밀번호가 틀렸는지, 막힌 계정인지 구분해 알려주지 않는다.
        raise _unauthorized("사번 또는 비밀번호가 올바르지 않습니다.")
    token, expires_at, user = result
    return LoginResponse(access_token=token, expires_at=expires_at, user=user)


@router.post("/auth/logout", status_code=204)
def logout(_: CurrentUser, credentials: Credentials, repo: Users) -> Response:
    repo.logout(credentials.credentials)
    return Response(status_code=204)


@router.get("/auth/me")
def me(user: CurrentUser) -> UserAccount:
    return user


@router.post("/auth/password", status_code=204)
def change_my_password(
    body: PasswordChange, user: CurrentUser, repo: Users
) -> Response:
    """본인 비밀번호 변경. 현재 비밀번호를 확인하고, 이 토큰을 포함한 모든 세션을 끊는다."""
    if not repo.check_password(user.employee_no, body.current_password):
        raise HTTPException(
            status_code=400, detail="현재 비밀번호가 올바르지 않습니다."
        )
    try:
        repo.set_password(user.employee_no, body.new_password)
    except ValueError as exc:
        raise _bad_password(exc) from exc
    return Response(status_code=204)


# --- 계정 관리 (관리자) ---


@router.get("/users")
def list_users(_: Admin, repo: Users) -> list[UserAccount]:
    return repo.list_users()


@router.post("/users", status_code=201)
def create_user(body: UserCreate, _: Admin, repo: Users) -> UserAccount:
    account = UserAccount(**body.model_dump(exclude={"password"}))
    try:
        return repo.create_user(account, body.password)
    except db.DuplicateUserError as exc:
        raise HTTPException(status_code=409, detail="이미 있는 사번입니다.") from exc
    except ValueError as exc:  # 비밀번호 규칙(공백뿐, 사번과 같음)
        raise _bad_password(exc) from exc


@router.patch("/users/{employee_no}")
def update_user(
    employee_no: str, body: UserUpdate, _: Admin, repo: Users
) -> UserAccount:
    try:
        return repo.update_user(employee_no, **body.model_dump(exclude_none=True))
    except db.UnknownUserError as exc:
        raise HTTPException(status_code=404, detail="없는 사번입니다.") from exc
    except db.LastAdminError as exc:
        raise HTTPException(
            status_code=409,
            detail="마지막 관리자입니다. 다른 관리자를 먼저 지정하세요.",
        ) from exc


@router.put("/users/{employee_no}/password", status_code=204)
def reset_password(
    employee_no: str, body: PasswordReset, _: Admin, repo: Users
) -> Response:
    """관리자가 비밀번호를 재설정한다. 그 사람의 세션은 모두 끊긴다."""
    try:
        repo.set_password(employee_no, body.password)
    except db.UnknownUserError as exc:
        raise HTTPException(status_code=404, detail="없는 사번입니다.") from exc
    except ValueError as exc:
        raise _bad_password(exc) from exc
    return Response(status_code=204)
