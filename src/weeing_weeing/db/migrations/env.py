"""Alembic 실행 환경. 연결은 migrate.upgrade가 넘기거나, 없으면 .env의 DATABASE_URL로 연다."""

from alembic import context

from weeing_weeing.config import get_settings
from weeing_weeing.db.engine import make_engine
from weeing_weeing.db.models import Base


def run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite ALTER 제약
    )
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    settings = get_settings()
    engine = make_engine(settings.database_url, timeout_s=settings.db_timeout_s)
    with engine.begin() as connection:
        run(connection)
