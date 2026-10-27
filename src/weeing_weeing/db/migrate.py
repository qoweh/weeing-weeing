"""스키마를 최신(head)으로 올린다. make db-migrate·make index·API 시작 때 쓴다.

마이그레이션 파일은 db/migrations/versions/. 새 마이그레이션 만들기(models.py를 고친 뒤):
    PYTHONPATH=src uv run --no-sync alembic revision --autogenerate -m "설명"
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    return config


def upgrade(engine: Engine) -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
