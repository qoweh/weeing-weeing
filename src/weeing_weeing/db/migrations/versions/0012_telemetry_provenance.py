"""15필드 센서 원본과 분리하여 송신자 출처·전송 주기를 보관한다."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "telemetry",
        sa.Column(
            "provenance",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("telemetry", "provenance")
