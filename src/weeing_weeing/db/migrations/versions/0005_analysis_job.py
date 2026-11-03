"""사건 자동 분석 작업과 중복 실행 방지 (#104)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_job",
        sa.Column("job_id", sa.String(32), primary_key=True),
        sa.Column(
            "incident_id",
            sa.String(64),
            sa.ForeignKey("incident.incident_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(160), unique=True, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "snapshot", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("analysis.id")),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED')",
            name="ck_analysis_job_status",
        ),
    )
    op.create_index("ix_analysis_job_incident_id", "analysis_job", ["incident_id"])
    op.create_index("ix_analysis_job_status", "analysis_job", ["status"])
    op.create_index(
        "uq_analysis_job_active",
        "analysis_job",
        ["incident_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('PENDING','RUNNING')"),
        postgresql_where=sa.text("status IN ('PENDING','RUNNING')"),
    )


def downgrade():
    op.drop_table("analysis_job")
