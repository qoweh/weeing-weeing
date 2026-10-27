"""문서 업로드 API: 저장 위치(git 밖), DB 기록, 충돌 거부, 색인(가짜 저장소), 개정판 교체."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from weeing_weeing.api import documents
from weeing_weeing.api.app import app
from weeing_weeing.db import interface as db
from weeing_weeing.db.documents import SqlDocuments
from weeing_weeing.rag import interface
from weeing_weeing.rag.indexer import DocumentIndexer

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / "data/manuals/BTT-MANUAL_v2.0.pdf"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(ROOT / "tests/rag"))
    from fakes import FakeEmbedder, MemoryVectorStore

    store = MemoryVectorStore({}, embedder=FakeEmbedder(), embedding_model="m")
    (tmp_path / "data").mkdir()
    catalog = tmp_path / "data/catalog.toml"
    shutil.copy(MANUAL, tmp_path / "data/m.pdf")
    catalog.write_text(
        '[[documents]]\ndoc_id = "BTT-MANUAL"\ndoc_version = "2.0"\ndoc_type = "manual"\n'
        'status = "approved"\npath = "m.pdf"\ntitle = "매뉴얼"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_CATALOG", str(catalog))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        interface, "get_indexer", lambda: DocumentIndexer(store, write_previews=True)
    )
    return store, tmp_path / "uploads"


def upload(content: bytes, *, name="manual.pdf", **form):
    data = {"doc_id": "UP-MANUAL", "doc_version": "1.0", "asset_id": "BLDC-001"}
    data.update(form)
    return TestClient(app).post(
        "/documents", files={"file": (name, content, "application/pdf")}, data=data
    )


def other_pdf() -> bytes:
    """카탈로그 파일과 내용이 다른 PDF(같은 본문 + 끝에 주석 한 줄)."""
    return MANUAL.read_bytes() + b"\n% upload test\n"


def test_upload_is_indexed_into_store_and_kept_outside_git(env):
    store, uploads = env
    response = upload(other_pdf())
    assert response.status_code == 202, response.text
    upload_id = response.json()["upload_id"]

    status = TestClient(app).get(f"/documents/{upload_id}").json()
    assert status["status"] == "completed", status
    assert status["chunk_count"] > 0
    folder = uploads / upload_id
    assert (folder / "manual.pdf").is_file()
    assert (folder / "chunks.md").is_file()  # 검토용 미리보기 유지

    chunk = store.chunks(where={"doc_id": "UP-MANUAL"})[0]
    assert chunk.chunk_id == "UP-MANUAL:1.0:0000"
    assert chunk.metadata["asset_id"] == "BLDC-001"
    assert chunk.metadata["upload_id"] == upload_id
    assert chunk.metadata["status"] == "approved"
    assert "citation" in chunk.metadata


def test_doc_id_of_catalog_is_rejected(env):
    _, uploads = env
    response = upload(other_pdf(), doc_id="BTT-MANUAL")
    assert response.status_code == 409
    assert "카탈로그" in response.json()["detail"]
    assert not any(uploads.iterdir())  # 저장한 파일도 지운다


def test_same_content_as_catalog_document_is_rejected(env):
    response = upload(MANUAL.read_bytes(), doc_id="UP-COPY")
    assert response.status_code == 409
    assert "같은 내용" in response.json()["detail"]


def test_new_version_upload_replaces_previous(env):
    store, uploads = env
    first = upload(other_pdf()).json()["upload_id"]
    second = upload(other_pdf() + b"% v2\n", doc_version="2.0").json()["upload_id"]

    versions = {c.doc_version for c in store.chunks(where={"doc_id": "UP-MANUAL"})}
    assert versions == {"2.0"}
    old = TestClient(app).get(f"/documents/{first}").json()
    assert (old["status"], old["superseded_by"]) == ("superseded", second)
    assert TestClient(app).get(f"/documents/{second}").json()["status"] == "completed"
    assert [
        r.upload_id for r in db.get_documents().listed() if r.origin == "upload"
    ] == [second]


def test_broken_pdf_fails_with_message(env):
    response = upload(b"%PDF-1.4 broken")
    status = TestClient(app).get(f"/documents/{response.json()['upload_id']}").json()
    assert status["status"] == "failed"
    assert "PDF" in status["error"]


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"name": "a.txt"}, 415),
        ({"doc_type": "regulation"}, 422),
        ({"doc_id": "A:B"}, 422),  # 청크 ID 구분자
    ],
)
def test_invalid_requests(env, kwargs, code):
    assert upload(other_pdf(), **kwargs).status_code == code


@pytest.mark.parametrize("doc_type", ["manual", "rule", "sop"])
def test_document_types_match_catalog_vocabulary(env, doc_type):
    assert upload(other_pdf(), doc_type=doc_type).status_code == 202


def test_unknown_upload_is_404(env):
    assert TestClient(app).get(f"/documents/{'0' * 32}").status_code == 404


def test_upload_dir_is_used_not_data_manuals(env):
    assert documents.upload_dir() == env[1]


# --- 리뷰 반영 ---


def test_uploaded_document_is_unchanged_on_next_make_index(env):
    """업로드 때 넣은 메타데이터와 make index가 계산하는 값이 같아 재색인되지 않는다."""
    from weeing_weeing.config import get_settings
    from weeing_weeing.rag.registry import catalog_from_records
    from weeing_weeing.rag.sync import sync

    store, uploads = env
    upload(other_pdf())
    catalog = catalog_from_records(
        db.get_documents().listed(),
        seed_root=get_settings().rag_catalog.parent,
        upload_dir=uploads,
    )
    report = sync(catalog, interface.get_indexer(), store)
    assert "UP-MANUAL" in report.unchanged


def test_relative_upload_dir_is_resolved_from_project_root(env, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", "storage/uploads-test")
    assert documents.upload_dir() == ROOT / "storage/uploads-test"


def test_filename_must_end_with_pdf_suffix(env):
    assert upload(other_pdf(), name=".pdf").status_code == 415


def test_broken_catalog_is_503_not_500(env, monkeypatch, tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[[documents]]\ndoc_id = "X"\n', encoding="utf-8")
    monkeypatch.setenv("RAG_CATALOG", str(bad))
    response = upload(other_pdf())
    assert response.status_code == 503
    assert not any(env[1].iterdir())


def test_older_upload_is_skipped_when_newer_exists(env, monkeypatch):
    """같은 doc_id의 새 업로드가 이미 있으면 예전 업로드는 색인하지 않고 superseded로 끝난다."""
    store, uploads = env
    monkeypatch.setattr(SqlDocuments, "newer_upload", lambda *a, **k: "newer-id")
    response = upload(other_pdf())
    status = TestClient(app).get(f"/documents/{response.json()['upload_id']}").json()
    assert status["status"] == "superseded"
    assert store.chunks(where={"doc_id": "UP-MANUAL"}) == []


# --- DB ---


def test_upload_is_recorded_in_db_without_manifest_file(env):
    _, uploads = env
    body = upload(other_pdf()).json()
    assert body["asset_id"] == "BLDC-001"  # 화면이 쓰던 응답 모양 유지
    assert body["source"] == f"{body['upload_id']}/manual.pdf"

    record = db.get_documents().get_upload(body["upload_id"])
    assert (record.origin, record.status) == ("upload", "completed")
    assert record.extra == {"asset_id": "BLDC-001"}
    assert not list(uploads.glob("*/metadata.json"))


def test_upload_checks_catalog_without_writing_seeds(env):
    """카탈로그 충돌은 파일 기준으로 보고, seed 반영은 make index만 한다."""
    assert upload(MANUAL.read_bytes(), doc_id="UP-COPY").status_code == 409
    upload(other_pdf())
    assert [r.origin for r in db.get_documents().listed()] == ["upload"]


def test_upload_is_not_indexed_over_catalog_document(env, monkeypatch):
    """접수 후 make index가 같은 doc_id를 카탈로그에 넣었다면 업로드는 색인하지 않는다."""
    from weeing_weeing.config import get_settings

    store, _ = env
    repo = db.get_documents()
    seed = interface.seed_records(get_settings().rag_catalog)[0]
    real_newer = SqlDocuments.newer_upload

    def seed_added_meanwhile(self, *args, **kwargs):  # 접수와 색인 사이에 make index
        self.sync_seed([seed, seed.model_copy(update={"doc_id": "UP-MANUAL"})])
        return real_newer(self, *args, **kwargs)

    monkeypatch.setattr(SqlDocuments, "newer_upload", seed_added_meanwhile)
    status = upload(other_pdf()).json()
    record = repo.get_upload(status["upload_id"])
    assert (record.status, record.superseded_by) == ("superseded", "seed")
    assert store.chunks(where={"doc_id": "UP-MANUAL"}) == []


def test_lost_completion_flags_winner_for_reindex(env, monkeypatch):
    """색인 중에 다른 쪽이 승자가 되면 이 업로드는 superseded, 승자에는 다시 색인 필요 표시."""
    repo = db.get_documents()
    real_complete = SqlDocuments.complete_upload

    def other_wins(self, upload_id, *, chunk_count):
        self.add_upload(
            documents.DocumentRecord(
                **{
                    **self.get_upload(upload_id).model_dump(),
                    "upload_id": "f" * 32,
                    "uploaded_at": self.get_upload(upload_id).uploaded_at
                    + __import__("datetime").timedelta(seconds=1),
                    "status": "queued",
                }
            )
        )
        real_complete(self, "f" * 32, chunk_count=1)
        return real_complete(self, upload_id, chunk_count=chunk_count)

    monkeypatch.setattr(SqlDocuments, "complete_upload", other_wins)
    body = upload(other_pdf()).json()
    assert repo.get_upload(body["upload_id"]).status == "superseded"
    [winner] = repo.listed()
    assert "덮어씀" in winner.index_error


def test_completion_error_marks_failed_not_stuck(env, monkeypatch):
    def broken(self, upload_id, *, chunk_count):
        raise RuntimeError("boom")

    monkeypatch.setattr(SqlDocuments, "complete_upload", broken)
    body = upload(other_pdf()).json()
    record = db.get_documents().get_upload(body["upload_id"])
    assert (record.status, record.error_type) == ("failed", "RuntimeError")


def test_database_down_is_503_and_leaves_no_files(env, monkeypatch):
    def down():
        raise db.DatabaseUnavailableError("OperationalError: connection refused")

    monkeypatch.setattr(db, "get_documents", down)
    response = upload(other_pdf())
    assert response.status_code == 503
    assert "DB" in response.json()["detail"]
    assert not any(env[1].iterdir())
    assert TestClient(app).get(f"/documents/{'0' * 32}").status_code == 503


def test_database_lost_during_indexing_is_logged_not_raised(env, monkeypatch, caplog):
    calls = []
    real = db.get_documents

    def flaky():
        calls.append(1)
        if len(calls) > 1:  # 접수는 되고, 백그라운드 색인에서 끊긴다
            raise db.DatabaseUnavailableError("OperationalError: gone")
        return real()

    monkeypatch.setattr(db, "get_documents", flaky)
    assert upload(other_pdf()).status_code == 202
    assert "상태 기록 실패" in caplog.text
