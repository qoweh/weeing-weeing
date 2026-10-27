"""테이블 정의. 스키마를 바꾸면 migrations/versions에 마이그레이션을 함께 추가한다.

PostgreSQL이 기준이고, 개발용 SQLite에서도 같은 정의가 동작해야 한다
(JSON은 PostgreSQL에서 JSONB, 부분 인덱스는 두 DB 모두 지원).
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


JsonColumn = JSON().with_variant(JSONB(), "postgresql")
COMPLETED = text("status = 'completed'")


class DocumentRow(Base):
    """문서 레지스트리. 필드 설명은 contracts/document.py."""

    __tablename__ = "document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upload_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    origin: Mapped[str] = mapped_column(String(16))
    doc_id: Mapped[str] = mapped_column(String(128), index=True)
    doc_version: Mapped[str] = mapped_column(String(128))
    doc_type: Mapped[str] = mapped_column(String(16))
    doc_status: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(1024))
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    stage: Mapped[str | None] = mapped_column(String(32))
    file_size: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(128))
    superseded_by: Mapped[str | None] = mapped_column(String(32))
    extra: Mapped[dict] = mapped_column(JsonColumn, default=dict)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    index_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # 같은 doc_id의 completed(색인 목록에 들어가는 행)는 하나뿐이다.
        Index(
            "uq_document_completed_doc_id",
            "doc_id",
            unique=True,
            postgresql_where=COMPLETED,
            sqlite_where=COMPLETED,
        ),
    )
