"""저장소 클래스가 함께 쓰는 트랜잭션·시각 처리.

연결 실패와 잠금 대기 초과는 DatabaseUnavailableError 하나로 알린다(API 503, 스크립트 종료 코드 2).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session, sessionmaker


class DatabaseUnavailableError(RuntimeError):
    """DB에 연결하지 못했거나 잠금 대기 시간이 지났다."""


def utc(value: datetime | None) -> datetime | None:
    """SQLite는 시간대를 저장하지 않으므로 항상 UTC로 쓰고, 읽을 때 UTC를 붙인다."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_values(values: dict[str, Any]) -> dict[str, Any]:
    return {k: utc(v) if isinstance(v, datetime) else v for k, v in values.items()}


def now() -> datetime:
    return datetime.now(UTC)


class Repository:
    """엔진 하나를 받아 트랜잭션 단위로 일하는 저장소의 공통 부분."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        try:
            with self._sessions.begin() as session:
                yield session
        except (OperationalError, InterfaceError) as exc:
            raise DatabaseUnavailableError(f"{type(exc).__name__}: {exc.orig}") from exc

    def _insert(self, table):
        """ON CONFLICT(업서트·중복 건너뛰기)를 쓰는 INSERT. PostgreSQL·SQLite 모두 지원한다."""
        dialect = postgresql if self._engine.dialect.name == "postgresql" else sqlite
        return dialect.insert(table)
