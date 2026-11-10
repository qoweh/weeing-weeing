"""로그인·계정 관리 API(#62): 토큰 발급·확인·폐기, 관리자 권한, 직책 권한 의존성."""

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from weeing_weeing.api.app import app
from weeing_weeing.api.auth import require_roles
from weeing_weeing.contracts import Role, UserAccount
from weeing_weeing.db import interface as db

PASSWORD = "correct-horse-1"


@pytest.fixture
def client(tmp_path, monkeypatch):

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    repo = db.get_users()
    repo.create_user(
        UserAccount(
            employee_no="A0001", name="관리자", role=Role.CONTROL, is_admin=True
        ),
        PASSWORD,
    )
    repo.create_user(
        UserAccount(employee_no="E1001", name="김점검", role=Role.INSPECTOR), PASSWORD
    )
    return TestClient(app)


def login(client, employee_no="A0001", password=PASSWORD) -> dict:
    response = client.post(
        "/auth/login", json={"employee_no": employee_no, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_me_logout(client):
    headers = login(client, "E1001")
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "현장 점검자"
    assert "password_hash" not in me.text

    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize(
    ("employee_no", "password"), [("E1001", "wrong-password"), ("없음", PASSWORD)]
)
def test_bad_login_is_401_without_detail(client, employee_no, password):
    response = client.post(
        "/auth/login", json={"employee_no": employee_no, "password": password}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "사번 또는 비밀번호가 올바르지 않습니다."
    assert response.headers["www-authenticate"] == "Bearer"


def test_missing_or_bad_token_is_401(client):
    assert client.get("/auth/me").status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.get("/auth/me", headers=bad).status_code == 401


def test_admin_manages_users(client):
    admin = login(client)
    created = client.post(
        "/users",
        headers=admin,
        json={
            "employee_no": "L2001",
            "name": "박팀장",
            "role": "보전 팀장",
            "password": PASSWORD,
        },
    )
    assert created.status_code == 201
    assert "password" not in created.json()
    again = client.post(
        "/users",
        headers=admin,
        json={
            "employee_no": "L2001",
            "name": "x",
            "role": "보전 팀장",
            "password": PASSWORD,
        },
    )
    assert again.status_code == 409

    listed = client.get("/users", headers=admin).json()
    assert [u["employee_no"] for u in listed] == ["A0001", "E1001", "L2001"]

    patched = client.patch("/users/L2001", headers=admin, json={"role": "현장 책임자"})
    assert patched.json()["role"] == "현장 책임자"
    assert patched.json()["name"] == "박팀장"  # 보내지 않은 칸은 그대로
    assert (
        client.patch("/users/없음", headers=admin, json={"name": "x"}).status_code
        == 404
    )


def test_non_admin_gets_403(client):
    inspector = login(client, "E1001")
    assert client.get("/users", headers=inspector).status_code == 403
    assert (
        client.patch(
            "/users/E1001", headers=inspector, json={"is_admin": True}
        ).status_code
        == 403
    )


def test_short_password_is_rejected(client):
    admin = login(client)
    response = client.post(
        "/users",
        headers=admin,
        json={
            "employee_no": "E1002",
            "name": "x",
            "role": "현장 점검자",
            "password": "short",
        },
    )
    assert response.status_code == 422


def test_last_admin_is_protected(client):
    admin = login(client)
    response = client.patch("/users/A0001", headers=admin, json={"is_admin": False})
    assert response.status_code == 409


def test_deactivate_ends_sessions(client):
    admin = login(client)
    inspector = login(client, "E1001")
    client.patch("/users/E1001", headers=admin, json={"is_active": False})

    assert client.get("/auth/me", headers=inspector).status_code == 401
    response = client.post(
        "/auth/login", json={"employee_no": "E1001", "password": PASSWORD}
    )
    assert response.status_code == 401


def test_password_change_and_reset(client):
    inspector = login(client, "E1001")
    wrong = client.post(
        "/auth/password",
        headers=inspector,
        json={"current_password": "wrong-password", "new_password": "new-password-2"},
    )
    assert wrong.status_code == 400
    changed = client.post(
        "/auth/password",
        headers=inspector,
        json={"current_password": PASSWORD, "new_password": "new-password-2"},
    )
    assert changed.status_code == 204
    assert client.get("/auth/me", headers=inspector).status_code == 401  # 세션 끊김
    login(client, "E1001", "new-password-2")

    admin = login(client)
    reset = client.put(
        "/users/E1001/password", headers=admin, json={"password": "reset-password-3"}
    )
    assert reset.status_code == 204
    login(client, "E1001", "reset-password-3")
    missing = client.put(
        "/users/없음/password", headers=admin, json={"password": "reset-password-3"}
    )
    assert missing.status_code == 404


def test_require_roles_dependency(client):
    router = APIRouter()

    @router.get(
        "/_test/lead-only", dependencies=[Depends(require_roles(Role.MAINT_LEAD))]
    )
    def lead_only() -> dict:
        return {"ok": True}

    app.include_router(router)
    try:
        # D-36: 관리자는 직책이 달라도 통과, 관리자가 아닌 다른 직책은 403
        admin = login(client)
        assert client.get("/_test/lead-only", headers=admin).json() == {"ok": True}
        assert client.get("/_test/lead-only").status_code == 401
        other = login(client, "E1001")
        assert client.get("/_test/lead-only", headers=other).status_code == 403
        client.patch("/users/E1001", headers=admin, json={"role": "보전 팀장"})
        lead = login(client, "E1001")
        assert client.get("/_test/lead-only", headers=lead).json() == {"ok": True}
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", "") != "/_test/lead-only"
        ]


def test_db_down_is_503(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:9/none")
    monkeypatch.setenv("DB_TIMEOUT_S", "1")
    response = TestClient(app).post(
        "/auth/login", json={"employee_no": "A0001", "password": PASSWORD}
    )
    assert response.status_code == 503


def test_password_rule_violation_is_422(client):
    admin = login(client)
    response = client.post(
        "/users",
        headers=admin,
        json={
            "employee_no": "E1002",
            "name": "x",
            "role": "현장 점검자",
            "password": "        ",
        },
    )
    assert response.status_code == 422
    reset = client.put(
        "/users/E1001/password", headers=admin, json={"password": "e1001e1001"}
    )
    assert reset.status_code == 204  # 사번과 다르면 통과
