from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from threading import Lock
from typing import TYPE_CHECKING, Any, ContextManager, Protocol

from weeing_weeing.contracts import (
    AnalysisResult,
    DocumentRecord,
    Incident,
    IncidentStatus,
    MaintenanceReport,
    ReportDocument,
    ReportDraft,
    ReportSummary,
    Role,
    TelemetryRecord,
    UserAccount,
)
from weeing_weeing.db.analysis_jobs import AnalysisConflictError, SqlAnalysisJobs
from weeing_weeing.db.documents import SeedResult
from weeing_weeing.db.incidents import UnknownIncidentError
from weeing_weeing.db.reports import (
    ReportConflictError,
    ReportForbiddenError,
    ReportIndexWork,
    ReportNotFoundError,
)
from weeing_weeing.db.session import DatabaseUnavailableError
from weeing_weeing.db.users import (
    MIN_PASSWORD_LENGTH,
    DuplicateUserError,
    LastAdminError,
    UnknownUserError,
)

if TYPE_CHECKING:
    from sqlalchemy import Engine

__all__ = [
    "AnalysisConflictError",
    "SqlAnalysisJobs",
    "get_analysis_jobs",
    "open_analysis_jobs",
    "DatabaseUnavailableError",
    "DocumentRepository",
    "MIN_PASSWORD_LENGTH",
    "DuplicateUserError",
    "IncidentRepository",
    "LastAdminError",
    "SeedResult",
    "TelemetryRepository",
    "UnknownIncidentError",
    "UnknownUserError",
    "UserRepository",
    "ReportRepository",
    "ReportIndexWork",
    "ReportConflictError",
    "ReportForbiddenError",
    "ReportNotFoundError",
    "get_reports",
    "open_reports",
    "get_documents",
    "get_incidents",
    "get_telemetry",
    "get_users",
    "open_documents",
    "open_incidents",
    "open_telemetry",
    "open_users",
]


class DocumentRepository(Protocol):
    """문서 레지스트리(document 테이블). 연결 실패는 DatabaseUnavailableError."""

    def listed(self) -> list[DocumentRecord]:
        """색인 목록: 카탈로그 문서(seed) + 완료된 업로드. doc_id마다 하나."""
        ...

    def sync_seed(self, records: Iterable[DocumentRecord]) -> SeedResult:
        """카탈로그 문서를 DB에 맞춘다(추가·수정·빠진 seed 삭제, doc_id가 겹친 업로드는 대체)."""
        ...

    def record_index_results(
        self, indexed: Iterable[str], failed: dict[str, str]
    ) -> None: ...

    def upload_conflict(self, doc_id: str, sha256: str) -> str | None:
        """새 업로드가 카탈로그·다른 문서와 부딪히면 이유를 돌려준다."""
        ...

    def add_upload(self, record: DocumentRecord) -> DocumentRecord: ...

    def get_upload(self, upload_id: str) -> DocumentRecord | None: ...

    def update_upload(self, upload_id: str, **changes: Any) -> DocumentRecord: ...

    def newer_upload(
        self, doc_id: str, uploaded_at: datetime, *, exclude: str
    ) -> str | None: ...

    def complete_upload(self, upload_id: str, *, chunk_count: int) -> DocumentRecord:
        """예전 completed를 superseded로, 이 업로드를 completed로(트랜잭션 하나)."""
        ...


class IncidentRepository(Protocol):
    """이상 사건과 AI 분석 결과(incident·analysis 테이블). 연결 실패는 DatabaseUnavailableError."""

    def save_incident(self, incident: Incident) -> Incident:
        """새 사건은 추가, 같은 incident_id는 최신 내용으로 덮어쓴다(갱신·회복).

        last_detected_at이 저장된 것보다 이른 내용(늦게 도착한 옛 갱신)은 무시한다.
        """
        ...

    def get_incident(self, incident_id: str) -> Incident | None: ...

    def list_incidents(
        self,
        *,
        asset_id: str | None = None,
        statuses: list[IncidentStatus] | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Incident]:
        """최근 발생순."""
        ...

    def save_analysis(self, result: AnalysisResult) -> int:
        """분석 결과 한 건 추가. 사건이 저장돼 있지 않으면 UnknownIncidentError."""
        ...

    def latest_analysis(self, incident_id: str) -> AnalysisResult | None: ...

    def list_analyses(
        self, incident_id: str, *, limit: int = 20
    ) -> list[AnalysisResult]: ...


class TelemetryRepository(Protocol):
    """센서 1초 데이터(telemetry 테이블). 같은 설비·같은 시각은 한 줄만 저장한다."""

    def save_many(self, records: Iterable[TelemetryRecord]) -> int:
        """새로 저장된 줄 수. 이미 있는 시각은 건너뛴다."""
        ...

    def between(
        self,
        asset_id: str,
        start: datetime,
        end: datetime,
        *,
        process_id: str | None = None,
        limit: int = 10_000,
    ) -> list[TelemetryRecord]:
        """[start, end) 구간, 시각순."""
        ...

    def latest(
        self, asset_id: str, *, process_id: str | None = None
    ) -> TelemetryRecord | None: ...


class UserRepository(Protocol):
    """사용자 계정과 로그인 세션(app_user·user_session). 비밀번호 원문·토큰 원문은 저장하지 않는다."""

    def create_user(self, account: UserAccount, password: str) -> UserAccount:
        """사번이 이미 있으면 DuplicateUserError, 비밀번호가 짧으면 ValueError."""
        ...

    def get_user(self, employee_no: str) -> UserAccount | None: ...

    def list_users(self) -> list[UserAccount]: ...

    def update_user(
        self,
        employee_no: str,
        *,
        name: str | None = None,
        role: Role | None = None,
        is_admin: bool | None = None,
        is_active: bool | None = None,
    ) -> UserAccount:
        """None인 칸은 그대로. 없는 사번은 UnknownUserError, 마지막 관리자를 없애면 LastAdminError."""
        ...

    def set_password(self, employee_no: str, password: str) -> None:
        """비밀번호 변경. 그 사람의 기존 세션은 모두 끊는다."""
        ...

    def check_password(self, employee_no: str, password: str) -> bool:
        """세션을 만들지 않고 비밀번호만 확인."""
        ...

    def login(
        self, employee_no: str, password: str, *, ttl: timedelta
    ) -> tuple[str, datetime, UserAccount] | None:
        """(토큰, 만료 시각, 계정). 틀리거나 비활성 계정이면 None(이유는 구분하지 않는다)."""
        ...

    def user_for_token(self, token: str) -> UserAccount | None: ...

    def logout(self, token: str) -> None: ...


class ReportRepository(Protocol):
    """보고서·버전·결재. actor_id는 인증된 사번, 수정은 조회한 revision이 필요하다."""

    def create_draft(self, actor_id: str, draft: ReportDraft) -> ReportDocument: ...

    def save_draft(
        self,
        actor_id: str,
        report_id: str,
        draft: ReportDraft,
        *,
        expected_revision: int,
    ) -> ReportDocument: ...

    def get_report(
        self,
        actor_id: str,
        report_id: str,
        *,
        version: int | None = None,
    ) -> ReportDocument: ...

    def list_reports(
        self,
        actor_id: str,
        *,
        review: bool = False,
        limit: int = 100,
    ) -> list[ReportSummary]: ...

    def transition(
        self,
        actor_id: str,
        report_id: str,
        action: str,
        *,
        expected_revision: int,
        comment: str = "",
    ) -> ReportDocument: ...

    def revise(
        self,
        actor_id: str,
        report_id: str,
        *,
        expected_revision: int,
    ) -> ReportDocument: ...

    def pending_index_reports(
        self,
        *,
        limit: int = 100,
        include_failed: bool = False,
        exclude_report_ids: frozenset[str] = frozenset(),
    ) -> list[MaintenanceReport]:
        """색인 대기 중인 최신 승인 판. exclude_report_ids는 한 실행 내 중복을 막는다."""
        ...

    def locked_index_job(
        self, report_id: str, *, include_failed: bool = False
    ) -> ContextManager[ReportIndexWork | None]:
        """승인 전환과 같은 보고서 행을 잠근 채 최신 판을 읽고 벡터 결과를 기록한다."""
        ...

    def record_index_result(
        self, report_id: str, version: int, *, success: bool
    ) -> None:
        """색인기 준비 실패 같은 벡터 쓰기 전 오류를 기록한다."""
        ...


def open_engine(url: str, *, timeout_s: float = 5) -> "Engine":
    """DB에 연결하고 스키마를 최신으로 올린 엔진. 저장소들이 이 엔진 하나를 함께 쓴다."""
    from sqlalchemy.exc import InterfaceError, OperationalError

    from weeing_weeing.db.engine import make_engine
    from weeing_weeing.db.migrate import upgrade

    engine = make_engine(url, timeout_s=timeout_s)
    try:
        upgrade(engine)
    except (OperationalError, InterfaceError) as exc:
        engine.dispose()
        raise DatabaseUnavailableError(f"{type(exc).__name__}: {exc.orig}") from exc
    return engine


def open_documents(url: str, *, timeout_s: float = 5) -> DocumentRepository:
    """DB에 연결하고 스키마를 최신으로 올린 뒤 저장소를 돌려준다."""
    from weeing_weeing.db.documents import SqlDocuments

    return SqlDocuments(open_engine(url, timeout_s=timeout_s))


def open_incidents(url: str, *, timeout_s: float = 5) -> IncidentRepository:
    from weeing_weeing.db.incidents import SqlIncidents

    return SqlIncidents(open_engine(url, timeout_s=timeout_s))


def open_users(url: str, *, timeout_s: float = 5) -> UserRepository:
    from weeing_weeing.db.users import SqlUsers

    return SqlUsers(open_engine(url, timeout_s=timeout_s))


def open_telemetry(url: str, *, timeout_s: float = 5) -> TelemetryRepository:
    from weeing_weeing.db.telemetry import SqlTelemetry

    return SqlTelemetry(open_engine(url, timeout_s=timeout_s))


def open_reports(url: str, *, timeout_s: float = 5) -> ReportRepository:
    from weeing_weeing.db.reports import SqlReports

    return SqlReports(open_engine(url, timeout_s=timeout_s))


@dataclass(frozen=True)
class _Shared:
    documents: DocumentRepository
    incidents: IncidentRepository
    telemetry: TelemetryRepository
    users: UserRepository
    reports: ReportRepository
    analysis_jobs: SqlAnalysisJobs


@lru_cache(maxsize=4)
def _cached(url: str, timeout_s: float) -> _Shared:
    from weeing_weeing.db.documents import SqlDocuments
    from weeing_weeing.db.incidents import SqlIncidents
    from weeing_weeing.db.reports import SqlReports
    from weeing_weeing.db.telemetry import SqlTelemetry
    from weeing_weeing.db.users import SqlUsers

    engine = open_engine(url, timeout_s=timeout_s)
    return _Shared(
        SqlDocuments(engine),
        SqlIncidents(engine),
        SqlTelemetry(engine),
        SqlUsers(engine),
        SqlReports(engine),
        SqlAnalysisJobs(engine),
    )


_OPEN_LOCK = Lock()


def _shared() -> _Shared:
    """.env의 DATABASE_URL로 연 저장소들. URL마다 한 번만 연결·마이그레이션하고 엔진을 함께 쓴다.

    API에서는 첫 요청 때 연다(DB가 꺼져 있어도 서버와 /health는 뜬다). 동시에 들어온
    첫 요청들이 마이그레이션을 두 번 돌리지 않게 잠근다.
    """
    from weeing_weeing.config import get_settings

    settings = get_settings()
    with _OPEN_LOCK:
        return _cached(settings.database_url, settings.db_timeout_s)


def get_documents() -> DocumentRepository:
    """.env의 DATABASE_URL로 연 문서 저장소."""
    return _shared().documents


def get_incidents() -> IncidentRepository:
    """.env의 DATABASE_URL로 연 사건·분석 저장소."""
    return _shared().incidents


def get_telemetry() -> TelemetryRepository:
    """.env의 DATABASE_URL로 연 센서 데이터 저장소."""
    return _shared().telemetry


def get_users() -> UserRepository:
    """.env의 DATABASE_URL로 연 사용자·세션 저장소."""
    return _shared().users


def get_reports() -> ReportRepository:
    """.env의 DATABASE_URL로 연 보고서·결재 저장소."""
    return _shared().reports


def get_analysis_jobs() -> SqlAnalysisJobs:
    """사건·센서·분석 작업을 함께 저장하는 #104 공개 진입점."""
    return _shared().analysis_jobs


def open_analysis_jobs(url: str, *, timeout_s: float = 5) -> SqlAnalysisJobs:
    """독립 환경·시연용 작업 저장소. 호출자가 엔진 수명을 관리한다."""
    return SqlAnalysisJobs(open_engine(url, timeout_s=timeout_s))
