"""마이그레이션과 ORM 모델이 어긋나지 않는지 확인한다.

모델만 고치고 마이그레이션을 빠뜨리면(또는 반대) 운영 DB와 코드가 조용히 달라진다.
"""

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from weeing_weeing.db.interface import open_engine
from weeing_weeing.db.models import Base

MIGRATIONS = Path(__file__).parents[2] / "src/weeing_weeing/db/migrations"


def test_migration_chain_has_single_head():
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1


def test_migrated_schema_matches_models(database_url):
    engine = open_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True}
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()
