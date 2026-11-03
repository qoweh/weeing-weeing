"""삭제한 보고서 번호 재사용 방지."""

import sqlalchemy as sa
from alembic import op
from alembic.script import ScriptDirectory

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    chat_tables = ("chat_conversation", "chat_request", "chat_message", "chat_feedback")
    existing = [name for name in chat_tables if inspector.has_table(name)]
    if existing and len(existing) != len(chat_tables):
        raise RuntimeError(
            "대화 저장 테이블이 일부만 존재합니다. DB 상태를 확인하세요."
        )
    if not existing:
        # 보고서 브랜치의 이전 0007이 이미 적용된 로컬 DB도 보존한다.
        scripts = ScriptDirectory.from_config(op.get_context().config)
        scripts.get_revision("0007").module.upgrade()
    if not sa.inspect(op.get_bind()).has_table("deleted_report_number"):
        op.create_table(
            "deleted_report_number",
            sa.Column("report_id", sa.String(64), primary_key=True),
        )


def downgrade():
    op.drop_table("deleted_report_number")
