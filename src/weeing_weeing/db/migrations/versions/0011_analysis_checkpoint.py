"""완료 단계와 센서 조회 결과를 보존하는 사건 분석 재개 입력."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_checkpoint",
        sa.Column(
            "job_id",
            sa.String(32),
            sa.ForeignKey("analysis_job.job_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "data", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("analysis_checkpoint")
