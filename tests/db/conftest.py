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
from weeing_weeing.db.models import Base

# 새 테이블도 빠지지 않도록 모델 전체를 외래 키의 역순으로 지운다.
TABLES = tuple(table.name for table in reversed(Base.metadata.sorted_tables))
BACKENDS = ["sqlite"]
if os.environ.get("TEST_DATABASE_URL"):
    BACKENDS.append("postgresql")


def _worker_url(url: str) -> str:
    """pytest-xdist 작업자마다 다른 DB를 쓴다(테스트마다 표를 비우므로 같이 쓰면 섞인다).

    작업자가 없으면(-n 없이 실행) 그대로다. 없는 DB는 같은 서버에 만든다(테스트 전용 DB만).
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return url
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    target = make_url(url)
    name = f"{target.database}_{worker}"
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()
    return target.set(database=name).render_as_string(hide_password=False)


@pytest.fixture(params=BACKENDS)
def database_url(request, tmp_path):
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'test.db'}"
    url = _worker_url(os.environ["TEST_DATABASE_URL"])
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
def users(database_url):

    repo = open_users(database_url)
    yield repo
    repo._engine.dispose()


@pytest.fixture
def reports(database_url):
    repo = open_reports(database_url)
    yield repo
    repo._engine.dispose()
