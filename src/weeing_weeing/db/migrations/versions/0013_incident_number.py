"""사건 표시 번호와 에러코드·날짜별 순번을 저장한다."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("incident", sa.Column("incident_number", sa.String(128)))
    op.create_index(
        "ix_incident_number_unique", "incident", ["incident_number"], unique=True
    )
    op.create_table(
        "incident_number_counter",
        sa.Column("prefix", sa.String(120), primary_key=True),
        sa.Column("last_number", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("incident_number_counter")
    op.drop_index("ix_incident_number_unique", table_name="incident")
    op.drop_column("incident", "incident_number")
