"""DB 테스트 fixture. SQLite(임시 파일)로 항상 돌고, TEST_DATABASE_URL이 있으면 PostgreSQL에서도 돈다.

    make db-up
    TEST_DATABASE_URL=postgresql://weeing:weeing@localhost:5432/weeing uv run --no-sync pytest tests/db

PostgreSQL 쪽은 테스트마다 document 테이블을 비운다. 실제 데이터가 있는 DB를 쓰지 않는다.
"""

import os

import pytest
from sqlalchemy import text

from weeing_weeing.db.interface import open_documents

BACKENDS = ["sqlite"]
if os.environ.get("TEST_DATABASE_URL"):
    BACKENDS.append("postgresql")


@pytest.fixture(params=BACKENDS)
def database_url(request, tmp_path):
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'test.db'}"
    url = os.environ["TEST_DATABASE_URL"]
    repo = open_documents(url)
    with repo._engine.begin() as connection:
        connection.execute(text("DELETE FROM document"))
    repo._engine.dispose()
    return url


@pytest.fixture
def repo(database_url):
    repo = open_documents(database_url)
    yield repo
    repo._engine.dispose()
