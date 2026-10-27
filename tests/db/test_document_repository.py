"""document 테이블: seed 반영, 업로드 상태, 개정판 대체(트랜잭션), 제약, 마이그레이션."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from weeing_weeing.config import PROJECT_ROOT
from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.db.documents import SqlDocuments
from weeing_weeing.db.engine import normalize_url
from weeing_weeing.db.interface import (
    DatabaseUnavailableError,
    get_documents,
    open_documents,
)
from weeing_weeing.db.models import Base, DocumentRow

# 진행 중 업로드는 STALE_AFTER(1시간)가 지나면 멈춘 것으로 보므로 지금 기준으로 잡는다.
T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)


def seed(doc_id="BTT-MANUAL", **overrides) -> DocumentRecord:
    values = dict(
        doc_id=doc_id,
        doc_version="2.0",
        doc_type="manual",
        origin="seed",
        title=doc_id,
        source=f"{doc_id}.pdf",
        source_sha256=f"sha-{doc_id}",
    )
    return DocumentRecord(**{**values, **overrides})


def upload(upload_id="u1", doc_id="UP-A", at=T0, **overrides) -> DocumentRecord:
    values = dict(
        doc_id=doc_id,
        doc_version="1.0",
        doc_type="manual",
        origin="upload",
        upload_id=upload_id,
        title="doc.pdf",
        source=f"{upload_id}/doc.pdf",
        source_sha256=f"sha-{upload_id}",
        extra={"asset_id": "BLDC-001"},
        uploaded_at=at,
        status="queued",
        stage="queued",
    )
    return DocumentRecord(**{**values, **overrides})


def statuses(repo) -> dict[str, str]:
    return {
        u: repo.get_upload(u).status for u in ("u1", "u2", "u3") if repo.get_upload(u)
    }


# --- 스키마 ---


def test_migration_matches_models(repo):
    with repo._engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_migration_is_idempotent(database_url):
    open_documents(database_url)._engine.dispose()
    repo = open_documents(database_url)  # 이미 최신이면 아무것도 하지 않는다
    assert repo.listed() == []


# --- seed(카탈로그) ---


def test_seed_sync_adds_updates_and_removes(repo):
    result = repo.sync_seed([seed("A"), seed("B")])
    assert (result.added, result.updated, result.removed) == (["A", "B"], [], [])

    again = repo.sync_seed([seed("A"), seed("B")])
    assert (again.added, again.updated, again.removed) == ([], [], [])  # 멱등

    changed = repo.sync_seed([seed("A", doc_version="3.0")])
    assert (changed.updated, changed.removed) == (["A"], ["B"])
    [record] = repo.listed()
    assert (record.doc_id, record.doc_version, record.status) == (
        "A",
        "3.0",
        "completed",
    )


def test_seed_extra_is_stored_as_json(repo):
    repo.sync_seed([seed("A", extra={"line": "BTT-2"})])
    assert repo.listed()[0].extra == {"line": "BTT-2"}
    assert repo.sync_seed([seed("A", extra={"line": "BTT-3"})]).updated == ["A"]


def test_seed_rejects_non_seed_records(repo):
    with pytest.raises(ValueError, match="seed"):
        repo.sync_seed([upload()])


def test_new_seed_supersedes_completed_upload_with_same_doc_id(repo):
    repo.add_upload(upload(doc_id="X"))
    repo.complete_upload("u1", chunk_count=3)

    result = repo.sync_seed([seed("X")])
    assert result.superseded == ["u1"]
    old = repo.get_upload("u1")
    assert (old.status, old.superseded_by) == ("superseded", "seed")
    assert [(r.doc_id, r.origin) for r in repo.listed()] == [("X", "seed")]


# --- 업로드 ---


def test_upload_lifecycle(repo):
    repo.add_upload(upload())
    assert repo.listed() == []  # 완료 전에는 목록에 없다

    repo.update_upload("u1", status="processing", stage="parsing")
    assert repo.get_upload("u1").stage == "parsing"

    done = repo.complete_upload("u1", chunk_count=7)
    assert (done.status, done.chunk_count) == ("completed", 7)
    assert done.completed_at is not None and done.completed_at.tzinfo is not None
    assert done.uploaded_at == T0
    assert [r.upload_id for r in repo.listed()] == ["u1"]
    assert repo.listed()[0].extra == {"asset_id": "BLDC-001"}


def test_get_unknown_upload_is_none(repo):
    assert repo.get_upload("없음") is None
    with pytest.raises(KeyError):
        repo.update_upload("없음", stage="x")


def test_completed_only_through_complete_upload(repo):
    repo.add_upload(upload())
    with pytest.raises(ValueError, match="complete_upload"):
        repo.update_upload("u1", status="completed")
    with pytest.raises(ValueError):
        repo.add_upload(upload("u2", status="completed"))


def test_update_validates_values(repo):
    repo.add_upload(upload())
    with pytest.raises(ValueError):
        repo.update_upload("u1", status="done")
    assert repo.get_upload("u1").status == "queued"


def test_new_version_supersedes_previous_in_one_step(repo):
    repo.add_upload(upload("u1"))
    repo.complete_upload("u1", chunk_count=3)
    repo.add_upload(upload("u2", at=T0 + timedelta(hours=1), doc_version="2.0"))
    repo.complete_upload("u2", chunk_count=4)

    assert statuses(repo) == {"u1": "superseded", "u2": "completed"}
    assert repo.get_upload("u1").superseded_by == "u2"
    assert [(r.doc_id, r.doc_version) for r in repo.listed()] == [("UP-A", "2.0")]


def test_older_upload_finishing_late_does_not_replace_newer(repo):
    repo.add_upload(upload("u1"))
    repo.add_upload(upload("u2", at=T0 + timedelta(hours=1)))
    repo.complete_upload("u2", chunk_count=4)
    late = repo.complete_upload("u1", chunk_count=3)

    assert (late.status, late.superseded_by) == ("superseded", "u2")
    assert [r.upload_id for r in repo.listed()] == ["u2"]


def test_upload_cannot_replace_seed(repo):
    repo.sync_seed([seed("X")])
    repo.add_upload(upload(doc_id="X"))
    assert repo.complete_upload("u1", chunk_count=1).superseded_by == "seed"
    assert [r.origin for r in repo.listed()] == ["seed"]


def test_database_enforces_one_completed_per_doc_id(repo):
    repo.add_upload(upload("u1"))
    repo.add_upload(upload("u2"))
    repo.complete_upload("u1", chunk_count=1)
    with pytest.raises(IntegrityError), repo._sessions.begin() as session:
        row = session.query(DocumentRow).filter_by(upload_id="u2").one()
        row.status = "completed"


def test_upload_id_is_unique(repo):
    repo.add_upload(upload("u1"))
    with pytest.raises(IntegrityError):
        repo.add_upload(upload("u1", doc_id="UP-B"))


def test_newer_upload_lookup(repo):
    repo.add_upload(upload("u1"))
    repo.add_upload(upload("u2", at=T0 + timedelta(hours=1)))
    repo.add_upload(upload("u3", doc_id="UP-B", at=T0 + timedelta(hours=2)))

    assert repo.newer_upload("UP-A", T0, exclude="u1") == "u2"
    assert repo.newer_upload("UP-A", T0 + timedelta(hours=1), exclude="u2") is None
    repo.update_upload("u2", status="failed")
    assert repo.newer_upload("UP-A", T0, exclude="u1") is None  # 실패한 것은 제외


def test_upload_conflicts(repo):
    repo.sync_seed([seed("BTT-MANUAL")])
    repo.add_upload(upload("u1", doc_id="UP-A", source_sha256="aaa"))

    assert "카탈로그" in repo.upload_conflict("BTT-MANUAL", "new")
    assert "같은 내용" in repo.upload_conflict("UP-NEW", "sha-BTT-MANUAL")
    assert "같은 내용" in repo.upload_conflict("UP-NEW", "aaa")  # 진행 중 업로드 포함
    # 같은 doc_id의 개정판, 같은 파일의 같은 doc_id 재업로드는 허용
    assert repo.upload_conflict("UP-A", "new") is None
    assert repo.upload_conflict("UP-A", "aaa") is None
    assert repo.upload_conflict("UP-NEW", "new") is None

    repo.update_upload("u1", status="failed")
    assert (
        repo.upload_conflict("UP-NEW", "aaa") is None
    )  # 실패한 업로드는 비교하지 않는다


def test_record_index_results(repo):
    repo.sync_seed([seed("A"), seed("B")])
    repo.record_index_results(["A"], {"B": "RuntimeError: 파싱 실패"})

    by_id = {r.doc_id: r for r in repo.listed()}
    assert by_id["A"].indexed_at is not None and by_id["A"].index_error is None
    assert by_id["B"].index_error == "RuntimeError: 파싱 실패"
    repo.record_index_results(["B"], {})
    assert repo.listed()[1].index_error is None
    repo.record_index_results([], {})  # 아무것도 없으면 그냥 끝난다


# --- 연결 ---


def test_unreachable_database_raises_unavailable():
    with pytest.raises(DatabaseUnavailableError):
        open_documents("postgresql://nobody:x@127.0.0.1:9/none", timeout_s=1)


def test_postgresql_url_uses_psycopg3():
    assert normalize_url("postgresql://u:p@h:5432/d").startswith(
        "postgresql+psycopg://"
    )


def test_relative_sqlite_path_is_from_project_root():
    url = normalize_url("sqlite:///storage/test-relative.db")
    parsed = make_url(url)
    assert parsed.drivername == "sqlite"
    # URL rendering may escape the Windows drive separator and backslashes.
    # Verify the resolved database target, not a platform-dependent spelling.
    assert Path(parsed.database) == PROJECT_ROOT / "storage/test-relative.db"


def test_get_documents_reads_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")
    repo = get_documents()
    assert isinstance(repo, SqlDocuments)
    assert get_documents() is repo  # URL마다 한 번만 연결·마이그레이션
    assert (tmp_path / "env.db").is_file()


def test_stale_in_progress_upload_no_longer_blocks(repo):
    """색인이 끊겨 processing으로 남은 업로드가 같은 파일 재업로드를 영원히 막지 않는다."""
    old = T0 - timedelta(hours=2)
    repo.add_upload(upload("u1", doc_id="UP-A", at=old, source_sha256="aaa"))
    repo.update_upload("u1", status="processing", stage="parsing")

    assert repo.upload_conflict("UP-NEW", "aaa") is None
    assert repo.newer_upload("UP-A", old - timedelta(hours=1), exclude="x") is None


def test_non_utc_times_are_stored_as_utc(repo):
    from datetime import timezone

    kst = T0.astimezone(timezone(timedelta(hours=9)))
    repo.add_upload(upload("u1", at=kst))
    assert repo.get_upload("u1").uploaded_at == T0
    assert repo.newer_upload("UP-A", kst - timedelta(minutes=1), exclude="x") == "u1"


def test_concurrent_seed_insert_is_retried(repo, monkeypatch):
    """다른 프로세스가 같은 seed를 먼저 넣어 유니크 인덱스에 걸리면 한 번 다시 맞춘다."""
    other = open_documents(str(repo._engine.url.render_as_string(hide_password=False)))
    real = SqlDocuments._sync_seed
    calls = []

    def racing(self, records):
        if not calls:
            calls.append(1)
            other._sync_seed(records)  # 경쟁 프로세스가 먼저 커밋
            with self._transaction() as session:  # 같은 행을 또 넣는다 → IntegrityError
                session.add(DocumentRow(**{**records[0].model_dump(), "stage": "seed"}))
        return real(self, records)

    monkeypatch.setattr(SqlDocuments, "_sync_seed", racing)
    result = repo.sync_seed([seed("A")])
    assert result.added == []  # 다시 맞출 때는 이미 있다
    assert [r.doc_id for r in repo.listed()] == ["A"]
    other._engine.dispose()
