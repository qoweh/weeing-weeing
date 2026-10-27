"""테이블 정의. 스키마를 바꾸면 migrations/versions에 마이그레이션을 함께 추가한다.

PostgreSQL이 기준이고, 개발용 SQLite에서도 같은 정의가 동작해야 한다
(JSON은 PostgreSQL에서 JSONB, 부분 인덱스는 두 DB 모두 지원).
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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


class IncidentRow(Base):
    """이상 사건. 계약(contracts/incident.py) 전체는 data에, 조회에 쓰는 값은 칼럼으로 뽑는다.

    같은 현상이 이어지면 detector가 기존 Incident를 갱신하므로 incident_id로 덮어쓴다.
    """

    __tablename__ = "incident"

    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    process_id: Mapped[str] = mapped_column(String(64))
    asset_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(16))
    codes: Mapped[list] = mapped_column(JsonColumn)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rule_version: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JsonColumn)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_incident_asset_status", "asset_id", "status"),
        Index("ix_incident_first_detected_at", "first_detected_at"),
    )


class AnalysisRow(Base):
    """AI 분석 결과. 한 사건을 여러 번 분석할 수 있다(재분석·모델 비교). 최신은 generated_at."""

    __tablename__ = "analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("incident.incident_id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JsonColumn)


class TelemetryRow(Base):
    """센서 1초 집계 한 줄(contracts/telemetry.py, v3 15컬럼). 칼럼 이름은 계약과 같다.

    같은 설비·같은 시각은 한 줄만 둔다. 같은 CSV를 다시 재생해도 중복으로 쌓이지 않는다.
    """

    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    process_id: Mapped[str] = mapped_column(String(64))
    asset_id: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(16))
    infeed_present: Mapped[bool] = mapped_column(Boolean)
    outfeed_present: Mapped[bool] = mapped_column(Boolean)
    rpm: Mapped[float] = mapped_column(Float)
    dc_input_current_a: Mapped[float | None] = mapped_column(Float)
    dc_bus_voltage_v: Mapped[float] = mapped_column(Float)
    motor_housing_temp_c: Mapped[float | None] = mapped_column(Float)
    de_vibration_rms_g: Mapped[float] = mapped_column(Float)
    de_kurtosis: Mapped[float] = mapped_column(Float)
    nde_vibration_rms_g: Mapped[float] = mapped_column(Float)
    nde_kurtosis: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        # 중복 방지와 구간 조회(asset_id + 시각 범위·최신순)를 함께 맡는다. 앞 칼럼 순서가 중요하다.
        UniqueConstraint(
            "asset_id", "timestamp", "process_id", name="uq_telemetry_asset_time"
        ),
    )


class UserRow(Base):
    """사용자 계정(contracts/user.py UserAccount + 비밀번호 해시).

    PostgreSQL에서 user는 예약어라 테이블 이름을 app_user로 둔다.
    """

    __tablename__ = "app_user"

    employee_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionRow(Base):
    """로그인 세션. 토큰 원문은 저장하지 않고 SHA-256만 둔다(DB가 새도 토큰을 쓸 수 없게)."""

    __tablename__ = "user_session"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_no: Mapped[str] = mapped_column(
        String(32), ForeignKey("app_user.employee_no", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
