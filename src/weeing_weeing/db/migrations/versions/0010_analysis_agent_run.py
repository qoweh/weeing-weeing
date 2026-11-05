"""멀티에이전트 역할·시도별 결과와 근거 스냅샷."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_agent_run",
        sa.Column(
            "job_id",
            sa.String(32),
            sa.ForeignKey("analysis_job.job_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), primary_key=True),
        sa.Column("attempt", sa.Integer(), primary_key=True),
        sa.Column(
            "data", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("analysis_agent_run")
