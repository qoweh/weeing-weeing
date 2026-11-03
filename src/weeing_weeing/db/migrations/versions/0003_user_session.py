"""app_user·user_session 테이블(#62 회원 기능)

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

AT = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("employee_no", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", AT, nullable=False),
        sa.Column("updated_at", AT, nullable=False),
        sa.Column("last_login_at", AT, nullable=True),
    )
    op.create_table(
        "user_session",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "employee_no",
            sa.String(32),
            sa.ForeignKey("app_user.employee_no", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", AT, nullable=False),
        sa.Column("expires_at", AT, nullable=False),
    )
    op.create_index("ix_user_session_employee_no", "user_session", ["employee_no"])


def downgrade() -> None:
    op.drop_table("user_session")
    op.drop_table("app_user")
