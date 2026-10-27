"""문서 레지스트리(document 테이블) 저장·조회.

상태 변화는 모두 트랜잭션 하나로 끝낸다. 특히 "예전 것 superseded + 새것 completed"는
한 번에 커밋하고, 부분 유니크 인덱스가 같은 doc_id의 completed를 하나로 막는다.
"""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Engine, and_, or_, select
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.db.models import DocumentRow

IN_PROGRESS = ("queued", "processing")
# 이보다 오래 queued·processing인 업로드는 멈춘 것으로 본다(서버 재시작 등으로 색인이 끊김).
# 충돌 검사·최신 업로드 판정에서 빼서, 같은 파일을 다시 올릴 수 있게 한다.
STALE_AFTER = timedelta(hours=1)
SEED_FIELDS = (
    "doc_version",
    "doc_type",
    "doc_status",
    "title",
    "source",
    "source_sha256",
    "extra",
)


class DatabaseUnavailableError(RuntimeError):
    """DB에 연결하지 못했거나 잠금 대기 시간이 지났다."""


@dataclass
class SeedResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)  # 카탈로그에 밀린 upload_id


def _utc(value: datetime | None) -> datetime | None:
    """SQLite는 시간대를 저장하지 않으므로 항상 UTC로 쓰고, 읽을 때 UTC를 붙인다."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_values(values: dict[str, Any]) -> dict[str, Any]:
    return {k: _utc(v) if isinstance(v, datetime) else v for k, v in values.items()}


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


def _now() -> datetime:
    return datetime.now(UTC)


class SqlDocuments:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        try:
            with self._sessions.begin() as session:
                yield session
        except (OperationalError, InterfaceError) as exc:
            raise DatabaseUnavailableError(f"{type(exc).__name__}: {exc.orig}") from exc

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

    def sync_seed(self, records: Iterable[DocumentRecord]) -> SeedResult:
        """카탈로그 → seed 행. 추가·수정하고, 카탈로그에서 빠진 seed는 지운다.

        새 seed와 doc_id가 같은 완료된 업로드는 superseded로 돌린다(카탈로그가 우선).
        두 프로세스가 동시에 같은 seed를 넣다 유니크 인덱스에 걸리면 한 번 다시 맞춘다.
        """
        records = list(records)
        try:
            return self._sync_seed(records)
        except IntegrityError:
            return self._sync_seed(records)

    def _sync_seed(self, records: list[DocumentRecord]) -> SeedResult:
        result = SeedResult()
        with self._transaction() as session:
            existing = {
                row.doc_id: row
                for row in session.scalars(
                    select(DocumentRow).where(DocumentRow.origin == "seed")
                )
            }
            for record in records:
                if record.origin != "seed":
                    raise ValueError(f"{record.doc_id}: seed가 아닌 문서")
                row = existing.pop(record.doc_id, None)
                if row is not None:
                    changes = {
                        name: getattr(record, name)
                        for name in SEED_FIELDS
                        if getattr(row, name) != getattr(record, name)
                    }
                    if changes:
                        for name, value in changes.items():
                            setattr(row, name, value)
                        result.updated.append(record.doc_id)
                    continue
                for other in session.scalars(
                    select(DocumentRow).where(
                        DocumentRow.doc_id == record.doc_id,
                        DocumentRow.status == "completed",
                    )
                ):
                    other.status = other.stage = "superseded"
                    other.superseded_by = "seed"
                    result.superseded.append(other.upload_id or other.doc_id)
                session.flush()  # 부분 유니크 인덱스: 밀어낸 뒤에 넣는다
                session.add(
                    DocumentRow(
                        **record.model_dump(exclude={"status", "stage"}),
                        status="completed",
                        stage="seed",
                    )
                )
                result.added.append(record.doc_id)
            for doc_id, row in existing.items():
                session.delete(row)
                result.removed.append(doc_id)
        return result

    def record_index_results(
        self, indexed: Iterable[str], failed: dict[str, str]
    ) -> None:
        """make index 결과를 목록 행(completed)에 남긴다."""
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

    def upload_conflict(self, doc_id: str, sha256: str) -> str | None:
        """새 업로드가 기존 문서와 부딪히면 이유를, 아니면 None.

        같은 doc_id의 업로드는 개정판으로 보고 허용한다(완료되면 예전 것을 대체).
        진행 중인 업로드도 내용 비교에 넣는다(같은 파일을 동시에 두 번 올리는 경우).
        """
        with self._transaction() as session:
            seed = session.scalar(
                select(DocumentRow.id).where(
                    DocumentRow.origin == "seed", DocumentRow.doc_id == doc_id
                )
            )
            if seed is not None:
                return f"{doc_id}는 카탈로그(data/catalog.toml)가 관리하는 문서다. 다른 doc_id를 쓴다"
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
                return f"{same}와 같은 내용의 파일이다. 같은 문서가 두 번 검색·인용된다"
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
        이미 더 늦게 올린 업로드나 카탈로그 문서가 completed면 이 업로드가 superseded가 된다.
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
                    if other.origin != "upload"
                    or _utc(other.uploaded_at) > _utc(row.uploaded_at)
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
