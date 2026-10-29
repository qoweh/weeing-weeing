"""DATABASE_URL → SQLAlchemy 엔진. 연결 타임아웃을 건다.

- postgresql://… 는 psycopg 3 드라이버로 연다(SQLAlchemy 기본값은 psycopg2).
- sqlite:///상대경로 는 레포 루트 기준으로 푼다(API를 어디서 실행해도 같은 파일).
"""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url

from weeing_weeing.config import from_root


def normalize_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (
        None,
        "",
        ":memory:",
    ):
        path = from_root(Path(parsed.database))
        path.parent.mkdir(parents=True, exist_ok=True)
        parsed = parsed.set(database=str(path))
    return parsed.render_as_string(hide_password=False)


def make_engine(url: str, *, timeout_s: float) -> Engine:
    url = normalize_url(url)
    if make_url(url).get_backend_name() == "sqlite":
        engine = create_engine(
            url,
            # 업로드 색인은 백그라운드 스레드에서 돈다. 잠금은 timeout까지 기다린다.
            connect_args={"check_same_thread": False, "timeout": timeout_s},
        )
        event.listen(engine, "connect", _sqlite_pragmas)
        return engine
    # 연결·잠금·커넥션 풀 대기를 모두 timeout_s로 묶는다. 넘으면 OperationalError
    # → DatabaseUnavailableError(API 503).
    lock_ms = max(1, int(timeout_s * 1000))
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=timeout_s,
        connect_args={
            "connect_timeout": max(1, int(timeout_s)),
            "options": f"-c lock_timeout={lock_ms}",
        },
    )


def _sqlite_pragmas(connection, _record) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # 읽기가 쓰기를 기다리지 않게
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
