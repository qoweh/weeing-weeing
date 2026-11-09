"""Record database arrival time for the telemetry retention policy."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("telemetry", sa.Column("stored_at", sa.DateTime(timezone=True)))
    # Existing rows receive a three-minute grace period after migration.
    op.execute(
        "UPDATE telemetry SET stored_at = CURRENT_TIMESTAMP WHERE stored_at IS NULL"
    )
    with op.batch_alter_table("telemetry") as batch:
        batch.alter_column(
            "stored_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        batch.create_index("ix_telemetry_stored_at", ["stored_at"])


def downgrade():
    with op.batch_alter_table("telemetry") as batch:
        batch.drop_index("ix_telemetry_stored_at")
        batch.drop_column("stored_at")
