"""DB 테스트 fixture. SQLite(임시 파일)로 항상 돌고, TEST_DATABASE_URL이 있으면 PostgreSQL에서도 돈다.

    make db-up
    TEST_DATABASE_URL=postgresql://weeing:weeing@localhost:5432/weeing uv run --no-sync pytest tests/db

PostgreSQL 쪽은 테스트마다 모든 테이블을 비운다. 실제 데이터가 있는 DB를 쓰지 않는다.
"""

import os

import pytest
from sqlalchemy import text

from weeing_weeing.db.interface import (
    open_documents,
    open_engine,
    open_incidents,
    open_reports,
    open_telemetry,
    open_users,
)

# 외래 키 순서: 참조하는 쪽부터 지운다.
TABLES = (
    "analysis_job",
    "report_index_job",
    "approval",
    "report_version",
    "report",
    "user_session",
    "app_user",
    "analysis",
    "incident",
    "telemetry",
    "document",
)
BACKENDS = ["sqlite"]
if os.environ.get("TEST_DATABASE_URL"):
    BACKENDS.append("postgresql")


@pytest.fixture(params=BACKENDS)
def database_url(request, tmp_path):
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'test.db'}"
    url = os.environ["TEST_DATABASE_URL"]
    engine = open_engine(url)
    with engine.begin() as connection:
        for table in TABLES:
            connection.execute(text(f"DELETE FROM {table}"))  # noqa: S608 (고정 이름)
    engine.dispose()
    return url


@pytest.fixture
def repo(database_url):
    repo = open_documents(database_url)
    yield repo
    repo._engine.dispose()


@pytest.fixture
def incidents(database_url):
    repo = open_incidents(database_url)
    yield repo
    repo._engine.dispose()


@pytest.fixture
def telemetry(database_url):
    repo = open_telemetry(database_url)
    yield repo
    repo._engine.dispose()


@pytest.fixture
def users(database_url, monkeypatch):
    from weeing_weeing.db import users as module

    monkeypatch.setattr(module, "SCRYPT_N", 2**10)  # 테스트 속도. 형식·검증 경로는 같다
    repo = open_users(database_url)
    yield repo
    repo._engine.dispose()


@pytest.fixture
def reports(database_url):
    repo = open_reports(database_url)
    yield repo
    repo._engine.dispose()
