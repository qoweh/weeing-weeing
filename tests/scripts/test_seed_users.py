"""scripts/seed_users.py: 없는 사번만 만들고, 임의 비밀번호는 한 번만 출력한다."""

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest

from weeing_weeing.db import interface as db

ROOT = Path(__file__).resolve().parents[2]
TTL = timedelta(hours=1)


@pytest.fixture
def script(tmp_path, monkeypatch):
    from weeing_weeing.db import users as module

    monkeypatch.setattr(module, "SCRYPT_N", 2**10)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seed.db'}")
    spec = importlib.util.spec_from_file_location(
        "seed_users", ROOT / "scripts/seed_users.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(tmp_path):
    return db.open_users(f"sqlite:///{tmp_path / 'seed.db'}")


def test_seed_file_has_one_admin_and_every_role(script):
    accounts = script.load(script.SEED)
    assert [a.employee_no for a in accounts if a.is_admin] == ["ADMIN"]
    assert {a.role.value for a in accounts} == {
        "관제 담당자",
        "보전 팀장",
        "현장 책임자",
        "현장 점검자",
    }


def test_creates_missing_users_with_given_password(
    script, tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(script.getpass, "getpass", lambda _: "demo-password-1")
    assert script.main(["--ask-password"]) == 0
    out = capsys.readouterr().out
    assert "demo-password-1" not in out
    repo = _repo(tmp_path)
    assert len(repo.list_users()) == 5
    assert repo.login("ADMIN", "demo-password-1", ttl=TTL) is not None

    monkeypatch.setattr(script.getpass, "getpass", lambda _: "other-password-2")
    assert script.main(["--ask-password"]) == 0  # 두 번째는 건너뜀
    assert "[있음] ADMIN" in capsys.readouterr().out
    assert repo.login("ADMIN", "demo-password-1", ttl=TTL) is not None


def test_random_passwords_are_printed_once_and_work(script, tmp_path, capsys):
    assert script.main([]) == 0
    line = next(
        line for line in capsys.readouterr().out.splitlines() if "[생성] I4001" in line
    )
    password = line.rsplit("비밀번호: ", 1)[1]
    assert _repo(tmp_path).login("I4001", password, ttl=TTL) is not None


def test_short_password_and_db_down_exit_2(script, monkeypatch):
    monkeypatch.setattr(script.getpass, "getpass", lambda _: "short")
    assert script.main(["--ask-password"]) == 2
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:9/none")
    monkeypatch.setenv("DB_TIMEOUT_S", "1")
    assert script.main([]) == 2
