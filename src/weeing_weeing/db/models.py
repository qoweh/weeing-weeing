"""테이블 정의. 스키마를 바꾸면 migrations/versions에 마이그레이션을 함께 추가한다.

PostgreSQL이 기준이고, 개발용 SQLite에서도 같은 정의가 동작해야 한다
(JSON은 PostgreSQL에서 JSONB, 부분 인덱스는 두 DB 모두 지원).
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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
    incident_number: Mapped[str | None] = mapped_column(String(128))
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
        Index("ix_incident_number_unique", "incident_number", unique=True),
        Index("ix_incident_asset_status", "asset_id", "status"),
        Index("ix_incident_first_detected_at", "first_detected_at"),
    )


class IncidentNumberCounterRow(Base):
    """사건 삭제 후에도 에러코드·날짜별 발급 순번을 보존한다."""

    __tablename__ = "incident_number_counter"

    prefix: Mapped[str] = mapped_column(String(120), primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False)


class DeletedIncidentRow(Base):
    """삭제된 사건이 진행 중인 센서 세션에서 다시 생성되지 않도록 기록한다."""

    __tablename__ = "deleted_incident"

    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class AnalysisJobRow(Base):
    """자동 호출 1회/사건, 실행별 입력 스냅샷과 명시적 재시도 기록."""

    __tablename__ = "analysis_job"
    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("incident.incident_id", ondelete="CASCADE"), index=True
    )
    request_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    snapshot: Mapped[dict] = mapped_column(JsonColumn)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analysis.id"))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED')",
            name="ck_analysis_job_status",
        ),
        Index(
            "uq_analysis_job_active",
            "incident_id",
            unique=True,
            sqlite_where=text("status IN ('PENDING','RUNNING')"),
            postgresql_where=text("status IN ('PENDING','RUNNING')"),
        ),
    )


class AnalysisAgentRunRow(Base):
    """분석 작업 안의 역할·시도별 결과. 검색 지식과 분리한다."""

    __tablename__ = "analysis_agent_run"
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("analysis_job.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JsonColumn)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnalysisCheckpointRow(Base):
    """단계 재시도용 입력. 작업 삭제 시 단계 기록과 함께 삭제한다."""

    __tablename__ = "analysis_checkpoint"
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("analysis_job.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    data: Mapped[dict] = mapped_column(JsonColumn)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TelemetryRow(Base):
    """센서 1초 집계 한 줄(contracts/telemetry.py, v3 15컬럼). 칼럼 이름은 계약과 같다.

    같은 설비·같은 시각은 한 줄만 둔다. 같은 CSV를 다시 재생해도 중복으로 쌓이지 않는다.
    """

    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), index=True
    )
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
    provenance: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)

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


class DeletedReportNumberRow(Base):
    """삭제된 보고서 번호의 재사용을 막는다."""

    __tablename__ = "deleted_report_number"
    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class ReportRow(Base):
    """보고서 관리대장. 작성자·현재 버전·상태·변경 번호만 보관한다."""

    __tablename__ = "report"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    author_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("app_user.employee_no"), index=True
    )
    incident_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("incident.incident_id"), index=True
    )
    report_status: Mapped[str] = mapped_column(String(16), index=True)
    current_version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    data_origin: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "current_version > 0 AND revision > 0", name="ck_report_version"
        ),
        CheckConstraint(
            "report_status IN ('DRAFT','SUBMITTED','REVIEWED','APPROVED','REJECTED')",
            name="ck_report_status",
        ),
        CheckConstraint(
            "data_origin IN ('LIVE','REPLAY','SYNTHETIC')", name="ck_report_origin"
        ),
    )


class ReportVersionRow(Base):
    """제출된 판은 고정한다. data에는 폼·사건/AI 스냅샷·제출된 계약 전체를 보존한다."""

    __tablename__ = "report_version"

    report_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("report.report_id"), primary_key=True
    )
    version_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_name: Mapped[str] = mapped_column(String(64))
    report_status: Mapped[str] = mapped_column(String(16))
    data_origin: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict] = mapped_column(JsonColumn)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRow(Base):
    __tablename__ = "approval"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(String(64))
    version_no: Mapped[int] = mapped_column(Integer)
    step: Mapped[int] = mapped_column(Integer)
    employee_no: Mapped[str] = mapped_column(
        String(32), ForeignKey("app_user.employee_no")
    )
    role: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(8))
    comment: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "version_no"],
            ["report_version.report_id", "report_version.version_no"],
        ),
        UniqueConstraint("report_id", "version_no", "step", name="uq_approval_step"),
    )


class ReportIndexJobRow(Base):
    """승인 outbox. pending → indexed 또는 failed, 실패는 명시적 재시도."""

    __tablename__ = "report_index_job"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "version_no"],
            ["report_version.report_id", "report_version.version_no"],
        ),
    )


class ChatConversationRow(Base):
    """개인 대화. owner_id는 생성 후 바꾸지 않으며 관리자 열람 예외도 두지 않는다."""

    __tablename__ = "chat_conversation"
    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("app_user.employee_no", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(100))
    conditions: Mapped[dict] = mapped_column(JsonColumn)
    mode: Mapped[str] = mapped_column(String(8))
    next_sequence: Mapped[int] = mapped_column(Integer, default=1)
    active_request_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("mode IN ('FAQ','CHAT')", name="ck_chat_mode"),)


class ChatRequestRow(Base):
    """대화별 요청 ID로 실행을 예약한다. 실행 토큰은 외부 응답에 포함하지 않는다."""

    __tablename__ = "chat_request"
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversation.conversation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    submission: Mapped[dict] = mapped_column(JsonColumn)
    conditions: Mapped[dict] = mapped_column(JsonColumn)
    state: Mapped[str] = mapped_column(String(16))
    execution_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_sequence: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict | None] = mapped_column(JsonColumn)
    # 0007 스키마 호환용. 대화 저장 기능에서는 사용량을 읽거나 갱신하지 않는다.
    usage: Mapped[dict | None] = mapped_column(JsonColumn)
    retry_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "state IN ('RESERVED','RUNNING','COMPLETED','FAILED','UNKNOWN')",
            name="ck_chat_request_state",
        ),
    )


class ChatMessageRow(Base):
    __tablename__ = "chat_message"
    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "request_id"],
            ["chat_request.conversation_id", "chat_request.request_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "conversation_id", "request_id", "role", name="uq_chat_message_role"
        ),
        CheckConstraint("role IN ('user','assistant')", name="ck_chat_message_role"),
    )


class LegacyChatFeedbackRow(Base):
    """0007을 적용한 DB의 기존 데이터 보존용. 공개 저장소·API에서는 사용하지 않는다."""

    __tablename__ = "chat_feedback"
    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rating: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "request_id"],
            ["chat_request.conversation_id", "chat_request.request_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "rating IN ('HELPFUL','UNHELPFUL')", name="ck_chat_feedback_rating"
        ),
    )
