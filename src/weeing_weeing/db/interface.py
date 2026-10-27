from collections.abc import Iterable
from datetime import datetime
from functools import lru_cache
from threading import Lock
from typing import Any, Protocol

from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.db.documents import DatabaseUnavailableError, SeedResult

__all__ = [
    "DatabaseUnavailableError",
    "DocumentRepository",
    "SeedResult",
    "get_documents",
    "open_documents",
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


def open_documents(url: str, *, timeout_s: float = 5) -> DocumentRepository:
    """DB에 연결하고 스키마를 최신으로 올린 뒤 저장소를 돌려준다."""
    from sqlalchemy.exc import InterfaceError, OperationalError

    from weeing_weeing.db.documents import SqlDocuments
    from weeing_weeing.db.engine import make_engine
    from weeing_weeing.db.migrate import upgrade

    engine = make_engine(url, timeout_s=timeout_s)
    try:
        upgrade(engine)
    except (OperationalError, InterfaceError) as exc:
        engine.dispose()
        raise DatabaseUnavailableError(f"{type(exc).__name__}: {exc.orig}") from exc
    return SqlDocuments(engine)


@lru_cache(maxsize=4)
def _cached(url: str, timeout_s: float) -> DocumentRepository:
    return open_documents(url, timeout_s=timeout_s)


_OPEN_LOCK = Lock()


def get_documents() -> DocumentRepository:
    """.env의 DATABASE_URL로 연 저장소. URL마다 한 번만 연결·마이그레이션한다.

    API에서는 첫 요청 때 연다(DB가 꺼져 있어도 서버와 /health는 뜬다). 동시에 들어온
    첫 요청들이 마이그레이션을 두 번 돌리지 않게 잠근다.
    """
    from weeing_weeing.config import get_settings

    settings = get_settings()
    with _OPEN_LOCK:
        return _cached(settings.database_url, settings.db_timeout_s)
