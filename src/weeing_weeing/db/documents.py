"""문서 레지스트리(document 테이블) 저장·조회.

상태 변화는 모두 트랜잭션 하나로 끝낸다. 특히 "예전 것 superseded + 새것 completed"는
한 번에 커밋하고, 부분 유니크 인덱스가 같은 doc_id의 completed를 하나로 막는다.
"""

import hashlib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Connection, Engine, and_, or_, select, text
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.db.models import DocumentRow, ReportRow
from weeing_weeing.db.session import DatabaseUnavailableError, Repository
from weeing_weeing.db.session import now as _now
from weeing_weeing.db.session import utc as _utc
from weeing_weeing.db.session import utc_values as _utc_values

IN_PROGRESS = ("queued", "processing")
DELETION_STATES = ("deleting", "delete_failed")
MANAGED_TYPES = ("manual", "sop", "rule")


class DocumentNotFoundError(KeyError):
    """대상 등록 문서가 없다."""


class DocumentConflictError(ValueError):
    """문서가 변경되었거나 다른 작업이 진행 중이다."""


# 이보다 오래 queued·processing인 업로드는 멈춘 것으로 본다(서버 재시작 등으로 색인이 끊김).
# 충돌 검사·최신 업로드 판정에서 빼서, 같은 파일을 다시 올릴 수 있게 한다.
STALE_AFTER = timedelta(hours=1)


def _alive(now: datetime) -> ColumnElement[bool]:
    """완료됐거나, 진행 중이면서 멈춘 지 오래되지 않은 행."""
    return or_(
        DocumentRow.status == "completed",
        and_(
            DocumentRow.status.in_(IN_PROGRESS),
            DocumentRow.uploaded_at > now - STALE_AFTER,
        ),
    )


def to_record(row: DocumentRow) -> DocumentRecord:
    values = {name: getattr(row, name) for name in DocumentRecord.model_fields}
    for name in ("uploaded_at", "completed_at", "indexed_at"):
        values[name] = _utc(values[name])
    return DocumentRecord(**values)


__all__ = ["DatabaseUnavailableError", "SqlDocuments"]


class SqlDocuments(Repository):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine)
        self._active_session: ContextVar[Session | Connection | None] = ContextVar(
            f"document_session_{id(self)}", default=None
        )

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        active = self._active_session.get()
        if isinstance(active, Session):
            yield active
        elif isinstance(active, Connection):
            try:
                with (
                    Session(active, expire_on_commit=False) as session,
                    session.begin(),
                ):
                    yield session
            except (OperationalError, InterfaceError) as exc:
                raise DatabaseUnavailableError(
                    f"{type(exc).__name__}: {exc.orig}"
                ) from exc
        else:
            with super()._transaction() as session:
                yield session

    @contextmanager
    def lock_document(
        self, doc_id: str, *, source_sha256: str | None = None
    ) -> Iterator[None]:
        """색인·삭제를 직렬화한다. PostgreSQL은 진행 상태를 따로 커밋한다."""
        if self._active_session.get() is not None:
            raise RuntimeError("문서 잠금은 중첩할 수 없다")
        if self._engine.dialect.name == "sqlite":
            with self._transaction() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                token = self._active_session.set(session)
                try:
                    yield
                finally:
                    self._active_session.reset(token)
            return
        # 세션 잠금은 커밋 후에도 유지된다. 같은 연결에서 각 상태를 따로 커밋하므로
        # 업로드 파싱·청킹 중에도 다른 연결이 진행률을 조회할 수 있다.
        names = [doc_id]
        if source_sha256 is not None:
            # 서로 다른 문서 ID로 같은 PDF를 동시에 접수하는 경우도 직렬화한다.
            names.append(f"sha256:{source_sha256}")
        keys = sorted(
            {
                int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], signed=True)
                for name in names
            }
        )
        try:
            with self._engine.connect() as connection:
                acquired = []
                try:
                    for key in keys:
                        connection.execute(
                            text("SELECT pg_advisory_lock(:key)"), {"key": key}
                        )
                        acquired.append(key)
                        connection.commit()
                    token = self._active_session.set(connection)
                    try:
                        yield
                    finally:
                        self._active_session.reset(token)
                finally:
                    try:
                        connection.rollback()
                        for key in reversed(acquired):
                            connection.execute(
                                text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                            )
                            connection.commit()
                    except Exception:
                        connection.invalidate()  # 부분 획득·잠금 해제 오류도 풀에 남기지 않는다.
                        raise
        except (OperationalError, InterfaceError) as exc:
            raise DatabaseUnavailableError(f"{type(exc).__name__}: {exc.orig}") from exc

    def managed_documents(self) -> list[DocumentRecord]:
        """등록된 매뉴얼·SOP·룰과 삭제 재시도 대상. 보고서·삭제 완료 이력은 제외."""
        with self._transaction() as session:
            rows = session.scalars(
                select(DocumentRow)
                .where(
                    DocumentRow.doc_type.in_(MANAGED_TYPES),
                    DocumentRow.origin.in_(("seed", "upload")),
                    DocumentRow.status.in_(("completed", "deleting", "delete_failed")),
                )
                .order_by(DocumentRow.title, DocumentRow.doc_id)
            )
            # 삭제 시 과거 판도 같은 상태로 묶이므로 문서마다 최신 행만 표시한다.
            latest: dict[str, DocumentRow] = {}
            for row in rows:
                previous = latest.get(row.doc_id)
                if previous is None or row.id > previous.id:
                    latest[row.doc_id] = row
            return [to_record(row) for row in latest.values()]

    def begin_delete(
        self,
        doc_id: str,
        *,
        doc_version: str,
        source_sha256: str,
        upload_id: str | None,
    ) -> DocumentRecord:
        """lock_document 안에서 호출한다. 삭제 전 상태를 남기고 모든 판을 색인 대상에서 뺀다."""
        with self._transaction() as session:
            rows = session.scalars(
                select(DocumentRow)
                .where(DocumentRow.doc_id == doc_id)
                .order_by(DocumentRow.id.desc())
            ).all()
            active = [
                row
                for row in rows
                if row.status in ("completed", "deleting", "delete_failed")
            ]
            if not active or any(
                row.doc_type not in MANAGED_TYPES
                or row.origin not in ("seed", "upload")
                for row in rows
            ):
                raise DocumentNotFoundError(doc_id)
            row = active[0]
            if (row.doc_version, row.source_sha256, row.upload_id) != (
                doc_version,
                source_sha256,
                upload_id,
            ):
                raise DocumentConflictError(
                    "문서가 변경됐습니다. 목록을 새로고침한 뒤 다시 시도하세요."
                )
            if any(
                other.status in IN_PROGRESS
                and (_utc(other.uploaded_at) or _now()) > _now() - STALE_AFTER
                for other in rows
            ):
                raise DocumentConflictError(
                    "같은 문서의 등록이 진행 중입니다. 완료 후 삭제하세요."
                )
            for other in rows:
                other.status = other.stage = "deleting"
                other.error = other.error_type = None
            session.flush()
            return to_record(row)

    def finish_delete(self, doc_id: str, *, error: str | None = None) -> None:
        """성공하면 모든 판의 행을 실제 삭제한다. 실패 상태는 남겨서 재시도할 수 있게 한다."""
        with self._transaction() as session:
            for row in session.scalars(
                select(DocumentRow).where(
                    DocumentRow.doc_id == doc_id, DocumentRow.status == "deleting"
                )
            ):
                if error:
                    row.status = row.stage = "delete_failed"
                    row.error = error
                else:
                    session.delete(row)

    # --- 목록 ---

    def listed(self) -> list[DocumentRecord]:
        """색인 목록: completed 행 전부(seed + 완료된 업로드). doc_id 순."""
        with self._transaction() as session:
            rows = session.scalars(
                select(DocumentRow)
                .where(DocumentRow.status == "completed")
                .order_by(DocumentRow.doc_id)
            )
            return [to_record(row) for row in rows]

    def record_index_results(
        self, indexed: Iterable[str], failed: dict[str, str]
    ) -> None:
        """색인 결과를 현재 등록 행(completed)에 남긴다."""
        now = _now()
        outcomes = {doc_id: None for doc_id in indexed} | dict(failed)
        if not outcomes:
            return
        with self._transaction() as session:
            for row in session.scalars(
                select(DocumentRow).where(
                    DocumentRow.status == "completed",
                    DocumentRow.doc_id.in_(outcomes),
                )
            ):
                row.index_error = outcomes[row.doc_id]
                if row.index_error is None:
                    row.indexed_at = now

    # --- 업로드 ---

    def upload_target(self, doc_id: str) -> DocumentRecord | None:
        with self._transaction() as session:
            rows = session.scalars(
                select(DocumentRow)
                .where(DocumentRow.doc_id == doc_id, _alive(_now()))
                .order_by(DocumentRow.id.desc())
            ).all()
            if any(row.status in IN_PROGRESS for row in rows):
                raise DocumentConflictError(
                    "같은 문서 ID의 등록이 진행 중입니다. 완료 후 다시 시도하세요."
                )
            current = next((row for row in rows if row.status == "completed"), None)
            return to_record(current) if current else None

    def upload_conflict(self, doc_id: str, sha256: str) -> str | None:
        """현재 DB에 등록된 다른 문서와 해시가 겹치면 이유를 돌려준다.

        같은 doc_id의 교체 확인은 호출자가 잠금 안에서 별도로 검사한다.
        진행 중인 업로드도 내용 비교에 넣는다(같은 파일을 동시에 두 번 올리는 경우).
        """
        with self._transaction() as session:
            if session.get(ReportRow, doc_id) is not None:
                return "보고서와 같은 문서 ID로 등록할 수 없습니다."
            deleting = session.scalar(
                select(DocumentRow.id)
                .where(
                    DocumentRow.doc_id == doc_id,
                    DocumentRow.status.in_(("deleting", "delete_failed")),
                )
                .limit(1)
            )
            if deleting is not None:
                return "삭제가 완료되지 않은 문서입니다. 목록에서 삭제를 재시도하세요."
            same = session.scalar(
                select(DocumentRow.doc_id)
                .where(
                    DocumentRow.source_sha256 == sha256,
                    DocumentRow.doc_id != doc_id,
                    _alive(_now()),
                )
                .limit(1)
            )
            if same is not None:
                return f"이미 {same} 문서에 같은 내용의 파일이 등록되어 있습니다. 중복 등록할 수 없습니다."
            return None

    def add_upload(self, record: DocumentRecord) -> DocumentRecord:
        if record.origin != "upload" or record.status == "completed":
            raise ValueError("새 업로드는 origin=upload, 완료 전 상태로 넣는다")
        with self._transaction() as session:
            session.add(DocumentRow(**_utc_values(record.model_dump())))
        return record

    def get_upload(self, upload_id: str) -> DocumentRecord | None:
        with self._transaction() as session:
            row = session.scalar(
                select(DocumentRow).where(DocumentRow.upload_id == upload_id)
            )
            return to_record(row) if row else None

    def update_upload(self, upload_id: str, **changes: Any) -> DocumentRecord:
        """처리 단계·실패 사유 등을 바꾼다. 완료는 complete_upload로만 한다."""
        if changes.get("status") == "completed":
            raise ValueError("완료는 complete_upload로 기록한다")
        with self._transaction() as session:
            row = self._upload_row(session, upload_id)
            if row.status in DELETION_STATES:
                raise DocumentConflictError(
                    "삭제된 문서의 등록 상태를 변경할 수 없습니다."
                )
            record = to_record(row).model_copy(update=changes)
            DocumentRecord.model_validate(record.model_dump())  # 값 검증
            for name, value in _utc_values(changes).items():
                setattr(row, name, value)
            return to_record(row)

    def newer_upload(
        self, doc_id: str, uploaded_at: datetime, *, exclude: str
    ) -> str | None:
        """같은 doc_id로 더 늦게 올린 살아 있는 업로드의 upload_id(먼저 올린 것은 색인하지 않는다)."""
        with self._transaction() as session:
            return session.scalar(
                select(DocumentRow.upload_id)
                .where(
                    DocumentRow.origin == "upload",
                    DocumentRow.doc_id == doc_id,
                    DocumentRow.upload_id != exclude,
                    _alive(_now()),
                    DocumentRow.uploaded_at > _utc(uploaded_at),
                )
                .order_by(DocumentRow.uploaded_at.desc())
                .limit(1)
            )

    def complete_upload(self, upload_id: str, *, chunk_count: int) -> DocumentRecord:
        """색인 끝: 같은 doc_id의 예전 completed를 superseded로 바꾸고 이 업로드를 completed로.

        트랜잭션 하나라 둘 다 completed이거나 둘 다 아닌 순간이 없다.
        이미 더 늦게 올린 업로드가 completed면 이 업로드가 superseded가 된다.
        동시에 완료되어 유니크 인덱스에 걸리면 한 번 다시 판단한다.
        """
        try:
            return self._complete(upload_id, chunk_count)
        except IntegrityError:
            return self._complete(upload_id, chunk_count)

    def _complete(self, upload_id: str, chunk_count: int) -> DocumentRecord:
        now = _now()
        with self._transaction() as session:
            row = self._upload_row(session, upload_id)
            if row.status in DELETION_STATES:
                raise DocumentConflictError("삭제된 문서를 다시 색인할 수 없습니다.")
            others = session.scalars(
                select(DocumentRow).where(
                    DocumentRow.doc_id == row.doc_id,
                    DocumentRow.status == "completed",
                    DocumentRow.id != row.id,
                )
            ).all()
            winner = next(
                (
                    other
                    for other in others
                    if other.uploaded_at is not None
                    and _utc(other.uploaded_at) > _utc(row.uploaded_at)
                ),
                None,
            )
            if winner is not None:
                row.status = row.stage = "superseded"
                row.superseded_by = winner.upload_id or winner.origin
                return to_record(row)
            for other in others:
                other.status = other.stage = "superseded"
                other.superseded_by = upload_id
            session.flush()  # 부분 유니크 인덱스: 예전 것을 내린 뒤에 올린다
            row.status = row.stage = "completed"
            row.chunk_count = chunk_count
            row.completed_at = row.indexed_at = now
            row.error = row.error_type = row.index_error = None
            return to_record(row)

    @staticmethod
    def _upload_row(session: Session, upload_id: str) -> DocumentRow:
        row = session.scalar(
            select(DocumentRow).where(DocumentRow.upload_id == upload_id)
        )
        if row is None:
            raise KeyError(upload_id)
        return row
