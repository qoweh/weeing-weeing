"""보고서·버전·결재·승인 색인 대기 기록(#62)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

AT = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "report",
        sa.Column("report_id", sa.String(64), primary_key=True),
        sa.Column(
            "author_id",
            sa.String(32),
            sa.ForeignKey("app_user.employee_no"),
            nullable=False,
        ),
        sa.Column("incident_id", sa.String(64), sa.ForeignKey("incident.incident_id")),
        sa.Column("report_status", sa.String(16), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("data_origin", sa.String(16), nullable=False),
        sa.Column("created_at", AT, nullable=False),
        sa.Column("updated_at", AT, nullable=False),
        sa.CheckConstraint(
            "current_version > 0 AND revision > 0", name="ck_report_version"
        ),
        sa.CheckConstraint(
            "report_status IN ('DRAFT','SUBMITTED','REVIEWED','APPROVED','REJECTED')",
            name="ck_report_status",
        ),
        sa.CheckConstraint(
            "data_origin IN ('LIVE','REPLAY','SYNTHETIC')", name="ck_report_origin"
        ),
    )
    for column in ("author_id", "incident_id", "report_status"):
        op.create_index(f"ix_report_{column}", "report", [column])
    op.create_table(
        "report_version",
        sa.Column(
            "report_id",
            sa.String(64),
            sa.ForeignKey("report.report_id"),
            primary_key=True,
        ),
        sa.Column("version_no", sa.Integer(), primary_key=True),
        sa.Column("author_name", sa.String(64), nullable=False),
        sa.Column("report_status", sa.String(16), nullable=False),
        sa.Column("data_origin", sa.String(16), nullable=False),
        sa.Column(
            "data", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("created_at", AT, nullable=False),
        sa.Column("updated_at", AT, nullable=False),
    )
    op.create_table(
        "approval",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.String(64), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column(
            "employee_no",
            sa.String(32),
            sa.ForeignKey("app_user.employee_no"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(8), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("at", AT, nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id", "version_no"],
            ["report_version.report_id", "report_version.version_no"],
        ),
        sa.UniqueConstraint("report_id", "version_no", "step", name="uq_approval_step"),
    )
    op.create_table(
        "report_index_job",
        sa.Column("report_id", sa.String(64), primary_key=True),
        sa.Column("version_no", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", AT, nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id", "version_no"],
            ["report_version.report_id", "report_version.version_no"],
        ),
    )


def downgrade() -> None:
    op.drop_table("report_index_job")
    op.drop_table("approval")
    op.drop_table("report_version")
    op.drop_table("report")
