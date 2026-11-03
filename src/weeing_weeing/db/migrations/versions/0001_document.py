"""document 테이블(문서 레지스트리)

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

COMPLETED = sa.text("status = 'completed'")


def upgrade() -> None:
    op.create_table(
        "document",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("upload_id", sa.String(32), nullable=True, unique=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("doc_id", sa.String(128), nullable=False),
        sa.Column("doc_version", sa.String(128), nullable=False),
        sa.Column("doc_type", sa.String(16), nullable=False),
        sa.Column("doc_status", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("source", sa.String(1024), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(128), nullable=True),
        sa.Column("superseded_by", sa.String(32), nullable=True),
        sa.Column(
            "extra", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_document_doc_id", "document", ["doc_id"])
    op.create_index("ix_document_source_sha256", "document", ["source_sha256"])
    op.create_index(
        "uq_document_completed_doc_id",
        "document",
        ["doc_id"],
        unique=True,
        postgresql_where=COMPLETED,
        sqlite_where=COMPLETED,
    )


def downgrade() -> None:
    op.drop_table("document")
