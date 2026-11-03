"""삭제된 사건의 재생성 방지 기록."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "deleted_incident",
        sa.Column("incident_id", sa.String(64), primary_key=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("deleted_incident")
