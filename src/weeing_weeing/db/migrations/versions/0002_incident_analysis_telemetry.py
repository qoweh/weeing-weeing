"""incident·analysis·telemetry 테이블(#61, #63)

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")
AT = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "incident",
        sa.Column("incident_id", sa.String(64), primary_key=True),
        sa.Column("process_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("codes", JSON, nullable=False),
        sa.Column("first_detected_at", AT, nullable=False),
        sa.Column("confirmed_at", AT, nullable=True),
        sa.Column("last_detected_at", AT, nullable=False),
        sa.Column("recovered_at", AT, nullable=True),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("data", JSON, nullable=False),
        sa.Column("updated_at", AT, nullable=False),
    )
    op.create_index("ix_incident_asset_status", "incident", ["asset_id", "status"])
    op.create_index("ix_incident_first_detected_at", "incident", ["first_detected_at"])

    op.create_table(
        "analysis",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "incident_id",
            sa.String(64),
            sa.ForeignKey("incident.incident_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("generated_at", AT, nullable=False),
        sa.Column("data", JSON, nullable=False),
    )
    op.create_index("ix_analysis_incident_id", "analysis", ["incident_id"])

    op.create_table(
        "telemetry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("record_id", sa.String(64), nullable=False),
        sa.Column("timestamp", AT, nullable=False),
        sa.Column("process_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("infeed_present", sa.Boolean(), nullable=False),
        sa.Column("outfeed_present", sa.Boolean(), nullable=False),
        sa.Column("rpm", sa.Float(), nullable=False),
        sa.Column("dc_input_current_a", sa.Float(), nullable=True),
        sa.Column("dc_bus_voltage_v", sa.Float(), nullable=False),
        sa.Column("motor_housing_temp_c", sa.Float(), nullable=True),
        sa.Column("de_vibration_rms_g", sa.Float(), nullable=False),
        sa.Column("de_kurtosis", sa.Float(), nullable=False),
        sa.Column("nde_vibration_rms_g", sa.Float(), nullable=False),
        sa.Column("nde_kurtosis", sa.Float(), nullable=False),
        sa.UniqueConstraint(
            "asset_id", "timestamp", "process_id", name="uq_telemetry_asset_time"
        ),
    )


def downgrade() -> None:
    op.drop_table("telemetry")
    op.drop_table("analysis")
    op.drop_table("incident")
