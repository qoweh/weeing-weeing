"""app_user·user_session(#62): 계정, 비밀번호 해시, 세션 발급·만료·폐기, 마지막 관리자 보호."""

from datetime import timedelta

import pytest

from weeing_weeing.contracts import Role, UserAccount
from weeing_weeing.db import users as module
from weeing_weeing.db.interface import (
    DuplicateUserError,
    LastAdminError,
    UnknownUserError,
)
from weeing_weeing.db.models import UserRow

TTL = timedelta(hours=1)
PASSWORD = "correct-horse-1"


def account(no="E1001", **overrides) -> UserAccount:
    data = {"employee_no": no, "name": "김점검", "role": Role.INSPECTOR}
    return UserAccount(**(data | overrides))


def test_password_hash_round_trip():
    stored = module.hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert module.verify_password(PASSWORD, stored)
    assert not module.verify_password("wrong-password", stored)
    assert not module.verify_password(PASSWORD, "garbage")
    assert module.hash_password(PASSWORD) != stored  # 솔트가 매번 다르다
    with pytest.raises(ValueError, match="8자"):
        module.hash_password("short")


def test_create_get_list_and_duplicate(users):
    created = users.create_user(account(), PASSWORD)
    assert created.created_at is not None
    assert users.get_user("E1001") == created
    assert users.get_user("없음") is None
    with pytest.raises(DuplicateUserError):
        users.create_user(account(name="다른 사람"), PASSWORD)
    users.create_user(account("A0001", role=Role.CONTROL, is_admin=True), PASSWORD)
    assert [u.employee_no for u in users.list_users()] == ["A0001", "E1001"]


def test_password_is_not_stored_in_plain_text(users):
    users.create_user(account(), PASSWORD)
    with users._transaction() as session:
        assert PASSWORD not in session.get(UserRow, "E1001").password_hash


def test_login_issues_token_and_logout_revokes(users):
    users.create_user(account(), PASSWORD)
    assert users.login("E1001", "wrong-password", ttl=TTL) is None
    assert users.login("없는사번", PASSWORD, ttl=TTL) is None

    token, expires_at, user = users.login("E1001", PASSWORD, ttl=TTL)
    assert user.employee_no == "E1001" and user.last_login_at is not None
    assert expires_at > user.last_login_at
    assert users.user_for_token(token).employee_no == "E1001"
    assert users.user_for_token("다른-토큰") is None

    users.logout(token)
    assert users.user_for_token(token) is None


def test_expired_session_is_rejected(users):
    users.create_user(account(), PASSWORD)
    token, *_ = users.login("E1001", PASSWORD, ttl=timedelta(seconds=-1))
    assert users.user_for_token(token) is None


def test_deactivate_blocks_login_and_existing_sessions(users):
    users.create_user(account(), PASSWORD)
    token, *_ = users.login("E1001", PASSWORD, ttl=TTL)

    users.update_user("E1001", is_active=False)
    assert users.user_for_token(token) is None
    assert users.login("E1001", PASSWORD, ttl=TTL) is None


def test_password_change_ends_sessions(users):
    users.create_user(account(), PASSWORD)
    token, *_ = users.login("E1001", PASSWORD, ttl=TTL)

    users.set_password("E1001", "new-password-2")
    assert users.user_for_token(token) is None
    assert users.login("E1001", PASSWORD, ttl=TTL) is None
    assert users.login("E1001", "new-password-2", ttl=TTL) is not None


def test_update_fields_and_unknown_user(users):
    users.create_user(account(), PASSWORD)
    updated = users.update_user("E1001", name="김팀장", role=Role.MAINT_LEAD)
    assert (updated.name, updated.role) == ("김팀장", Role.MAINT_LEAD)
    assert users.get_user("E1001") == updated
    with pytest.raises(UnknownUserError):
        users.update_user("없음", name="x")
    with pytest.raises(UnknownUserError):
        users.set_password("없음", PASSWORD)


def test_last_admin_cannot_be_removed(users):
    users.create_user(account("A0001", is_admin=True), PASSWORD)
    with pytest.raises(LastAdminError):
        users.update_user("A0001", is_admin=False)
    with pytest.raises(LastAdminError):
        users.update_user("A0001", is_active=False)
    assert users.get_user("A0001").is_admin  # 실패한 변경은 되돌려진다

    users.create_user(account("A0002", is_admin=True), PASSWORD)
    assert not users.update_user("A0001", is_admin=False).is_admin


@pytest.mark.parametrize("password", ["        ", "short"])
def test_password_rules(users, password):
    with pytest.raises(ValueError):
        users.create_user(account(), password)


def test_password_equal_to_employee_no_is_rejected_on_change(users):
    users.create_user(account("LONGNO123"), PASSWORD)
    with pytest.raises(ValueError, match="사번"):
        users.set_password("LONGNO123", "longno123")


def test_token_with_extra_characters_is_rejected(users):
    users.create_user(account(), PASSWORD)
    token, *_ = users.login("E1001", PASSWORD, ttl=TTL)
    assert users.user_for_token(token + "é") is None
