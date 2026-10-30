"""개인 대화·중복 요청·메시지·피드백 저장 (#90). 기존 보고서/사용자 구조는 유지한다."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    data = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "chat_conversation",
        sa.Column("conversation_id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("app_user.employee_no", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("conditions", data, nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.Column("active_request_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('FAQ','CHAT')", name="ck_chat_mode"),
    )
    op.create_index("ix_chat_conversation_owner_id", "chat_conversation", ["owner_id"])
    op.create_table(
        "chat_request",
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("chat_conversation.conversation_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("submission", data, nullable=False),
        sa.Column("conditions", data, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("execution_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("user_sequence", sa.Integer(), nullable=False),
        sa.Column("response", data),
        sa.Column("usage", data),
        sa.Column("retry_allowed", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('RESERVED','RUNNING','COMPLETED','FAILED','UNKNOWN')",
            name="ck_chat_request_state",
        ),
    )
    op.create_table(
        "chat_message",
        sa.Column("conversation_id", sa.String(36), primary_key=True),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id", "request_id"],
            ["chat_request.conversation_id", "chat_request.request_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "conversation_id", "request_id", "role", name="uq_chat_message_role"
        ),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_chat_message_role"),
    )
    op.create_table(
        "chat_feedback",
        sa.Column("conversation_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("rating", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id", "request_id"],
            ["chat_request.conversation_id", "chat_request.request_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "rating IN ('HELPFUL','UNHELPFUL')", name="ck_chat_feedback_rating"
        ),
    )


def downgrade():
    for table in ("chat_feedback", "chat_message", "chat_request", "chat_conversation"):
        op.drop_table(table)
