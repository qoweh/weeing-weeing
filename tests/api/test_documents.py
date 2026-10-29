"""문서 업로드 API: 저장 위치(git 밖), DB 기록, 충돌 거부, 색인(가짜 저장소), 개정판 교체."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from weeing_weeing.api import documents
from weeing_weeing.api.app import app
from weeing_weeing.api.auth import current_user
from weeing_weeing.contracts import Role, UserAccount
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
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        interface, "get_indexer", lambda: DocumentIndexer(store, write_previews=True)
    )
    prior = dict(app.dependency_overrides)
    app.dependency_overrides[current_user] = lambda: UserAccount(
        employee_no="CONTROL", name="관제", role=Role.CONTROL
    )
    yield store, tmp_path / "uploads"
    app.dependency_overrides.clear()
    app.dependency_overrides.update(prior)


def upload(content: bytes, *, name="manual.pdf", **form):
    data = {"doc_id": "UP-MANUAL", "asset_id": "BLDC-001"}
    data.update(form)
    return TestClient(app).post(
        "/documents", files={"file": (name, content, "application/pdf")}, data=data
    )


def other_pdf() -> bytes:
    """업로드 검증용 PDF(원본 본문 + 끝에 주석 한 줄)."""
    return MANUAL.read_bytes() + b"\n% upload test\n"


@pytest.mark.parametrize(
    ("filename", "version"),
    [
        ("BTT-MANUAL_v2.0.pdf", "2.0"),
        ("점검 매뉴얼 v1.0.pdf", "1.0"),
        ("장비(V3.2).PDF", "3.2"),
        ("매뉴얼v2.1.3.pdf", "2.1.3"),
        ("v1.0_개정_v2.0.pdf", "2.0"),
        ("매뉴얼.pdf", "1.0"),
        ("매뉴얼_2026.10.29.pdf", "1.0"),
        ("manual_2.0.pdf", "1.0"),
        ("manual_v2.pdf", "1.0"),
        ("CV2.0.pdf", "1.0"),
        ("manual_v2.0beta.pdf", "1.0"),
        ("manual_v2.0.1beta.pdf", "1.0"),
        ("", "1.0"),
    ],
)
def test_version_from_filename(filename, version):
    assert documents._version_from_filename(filename) == version


@pytest.mark.parametrize(
    ("filename", "version"), [("manual_v2.0.pdf", "2.0"), ("manual.pdf", "1.0")]
)
def test_upload_uses_filename_version_ignoring_submitted_value(env, filename, version):
    response = upload(other_pdf(), name=filename, doc_version="99.9")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["doc_version"] == version
    assert db.get_documents().get_upload(body["upload_id"]).doc_version == version
    assert {chunk.doc_version for chunk in env[0].chunks()} == {version}


def test_overlong_filename_version_is_rejected_before_saving(env):
    response = upload(other_pdf(), name=f"manual_v{'1' * 127}.0.pdf")
    assert response.status_code == 422
    assert not env[1].exists()


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


def test_new_version_upload_replaces_previous(env):
    store, uploads = env
    first = upload(other_pdf()).json()["upload_id"]
    second = upload(other_pdf() + b"% v2\n", name="manual_v2.0.pdf").json()["upload_id"]

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
        ({"doc_id": "RPT-reserved"}, 422),  # 보고서 ID 영역 보호
    ],
)
def test_invalid_requests(env, kwargs, code):
    assert upload(other_pdf(), **kwargs).status_code == code


@pytest.mark.parametrize("doc_type", ["manual", "rule", "sop"])
def test_document_types_are_supported(env, doc_type):
    assert upload(other_pdf(), doc_type=doc_type).status_code == 202


def test_unknown_upload_is_404(env):
    assert TestClient(app).get(f"/documents/{'0' * 32}").status_code == 404


def test_upload_dir_is_used_not_data_manuals(env):
    assert documents.upload_dir() == env[1]


# --- 리뷰 반영 ---


def test_relative_upload_dir_is_resolved_from_project_root(env, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", "storage/uploads-test")
    assert documents.upload_dir() == ROOT / "storage/uploads-test"


def test_filename_must_end_with_pdf_suffix(env):
    assert upload(other_pdf(), name=".pdf").status_code == 415


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


# --- 매뉴얼 목록·삭제·권한 ---


def delete(body, doc_id="UP-MANUAL"):
    from urllib.parse import quote

    return TestClient(app).request(
        "DELETE",
        f"/documents/{quote(doc_id, safe='')}",
        json={
            "doc_version": body["doc_version"],
            "source_sha256": body["source_sha256"],
            "upload_id": body.get("upload_id"),
        },
    )


def test_list_documents_has_titles_and_excludes_report_and_superseded(env):
    repo = db.get_documents()
    add_legacy(repo, "BTT-MANUAL", title="매뉴얼")
    add_legacy(repo, "REPORT", doc_type="report")
    upload(other_pdf())
    upload(other_pdf() + b"%new", name="장비 점검_v2.0.pdf")
    response = TestClient(app).get("/documents")
    assert response.status_code == 200
    docs = {r["doc_id"]: r for r in response.json()}
    assert set(docs) == {"BTT-MANUAL", "UP-MANUAL"}
    assert docs["UP-MANUAL"]["title"] == "장비 점검_v2.0.pdf"
    assert docs["UP-MANUAL"]["doc_version"] == "2.0"
    assert docs["BTT-MANUAL"]["title"] == "매뉴얼"
    assert "source" not in docs["UP-MANUAL"]


@pytest.mark.parametrize("query", ["manual.pdf", "up-manual", "bldc-001"])
def test_document_search_keeps_metadata_search(env, query):
    upload(other_pdf())
    response = TestClient(app).get("/documents", params={"q": query})
    assert response.status_code == 200
    assert [item["doc_id"] for item in response.json()] == ["UP-MANUAL"]


def test_document_search_finds_korean_body_and_returns_only_short_excerpt(
    env, monkeypatch
):
    record = upload(other_pdf()).json()
    preview = env[1] / record["upload_id"] / "parsed.md"
    preview.write_text(
        "앞부분 " * 100 + "담당자 이순신은 설비를 점검했다." + " 뒷부분" * 100
    )
    monkeypatch.setattr(interface, "get_indexer", lambda: pytest.fail("벡터 DB 불필요"))
    client = TestClient(app)
    [found] = client.get("/documents", params={"q": "이순신"}).json()
    assert found["doc_id"] == "UP-MANUAL"
    excerpt = found["search_excerpt"]
    assert excerpt["match"] == "이순신"
    assert "담당자" in excerpt["before"] and "점검" in excerpt["after"]
    assert len("".join(excerpt.values())) < 150
    assert "search_excerpt" not in client.get("/documents").json()[0]
    assert client.get("/documents", params={"q": "없는이름"}).json() == []


def test_document_search_normalizes_whitespace_case_and_treats_symbols_literally(env):
    record = upload(other_pdf()).json()
    preview = env[1] / record["upload_id"] / "parsed.md"
    preview.write_text("이순신\n\n장군의 Motor-A+B[1] 점검")
    client = TestClient(app)
    for term in (" 이순신  장군 ", "motor-a+b[1]"):
        response = client.get("/documents", params={"q": term})
        assert response.status_code == 200
        assert response.json()[0]["doc_id"] == "UP-MANUAL"
    assert client.get("/documents", params={"q": ".*"}).json() == []
    assert len(client.get("/documents", params={"q": "  "}).json()) == 1
    assert client.get("/documents", params={"q": "a" * 201}).status_code == 422


def test_document_search_excludes_old_versions_and_deleted_files(env):
    first = upload(other_pdf()).json()
    (env[1] / first["upload_id"] / "parsed.md").write_text("이순신 구버전 전용 본문")
    second = upload(other_pdf() + b"%new", name="manual_v2.0.pdf").json()
    (env[1] / second["upload_id"] / "parsed.md").write_text("홍길동 현재 본문")
    client = TestClient(app)
    assert client.get("/documents", params={"q": "이순신"}).json() == []
    [found] = client.get("/documents", params={"q": "홍길동"}).json()
    assert found["doc_version"] == "2.0"
    assert delete(second).status_code == 200
    assert client.get("/documents", params={"q": "홍길동"}).json() == []


@pytest.mark.parametrize(
    "file_state", ["missing", "invalid_encoding", "outside_symlink"]
)
def test_document_search_unavailable_preview_keeps_metadata_and_cannot_read_outside(
    env, file_state
):
    record = upload(other_pdf()).json()
    preview = env[1] / record["upload_id"] / "parsed.md"
    preview.unlink()
    if file_state == "invalid_encoding":
        preview.write_bytes(b"\xff\xfe")
    elif file_state == "outside_symlink":
        outside = env[1].parent / "outside.md"
        outside.write_text("외부기밀")
        preview.symlink_to(outside)
    client = TestClient(app)
    assert client.get("/documents", params={"q": "외부기밀"}).json() == []
    response = client.get("/documents", params={"q": "UP-MANUAL"})
    assert response.status_code == 200
    assert response.json()[0]["doc_id"] == "UP-MANUAL"


@pytest.mark.parametrize("role", [Role.INSPECTOR, Role.MAINT_LEAD, Role.SITE_MANAGER])
@pytest.mark.parametrize("admin", [False, True])
def test_only_control_can_upload_and_delete_but_all_can_list(env, role, admin):
    body = upload(other_pdf()).json()
    app.dependency_overrides[current_user] = lambda: UserAccount(
        employee_no="OTHER", name="다른 직책", role=role, is_admin=admin
    )
    assert upload(other_pdf()).status_code == 403
    assert delete(body).status_code == 403
    assert TestClient(app).get("/documents").status_code == 200
    assert TestClient(app).get("/documents", params={"q": "manual"}).status_code == 200
    assert TestClient(app).get(f"/documents/{body['upload_id']}").status_code == 200
    assert env[0].chunks(where={"doc_id": "UP-MANUAL"})


def test_anonymous_document_requests_are_401(env):
    app.dependency_overrides.pop(current_user)
    assert upload(other_pdf()).status_code == 401
    client = TestClient(app)
    assert client.get("/documents").status_code == 401
    assert client.get("/documents", params={"q": "이순신"}).status_code == 401
    assert client.get(f"/documents/{'0' * 32}").status_code == 401
    assert (
        client.request(
            "DELETE", "/documents/X", json={"doc_version": "1", "source_sha256": "x"}
        ).status_code
        == 401
    )


def test_delete_removes_vectors_and_all_versions_preserving_originals(env):
    store, uploads = env
    first = upload(other_pdf()).json()
    second = upload(other_pdf() + b"%new", name="manual_v2.0.pdf").json()
    upload(other_pdf() + b"%other", doc_id="OTHER")
    response = delete(second)
    assert response.status_code == 200, response.text
    assert response.json()["removed_chunks"] > 0
    assert not store.chunks(where={"doc_id": "UP-MANUAL"})
    assert store.chunks(where={"doc_id": "OTHER"})
    assert [r["doc_id"] for r in TestClient(app).get("/documents").json()] == ["OTHER"]
    repo = db.get_documents()
    assert repo.get_upload(first["upload_id"]) is None
    assert repo.get_upload(second["upload_id"]) is None
    assert (uploads / second["upload_id"] / "manual_v2.0.pdf").exists()
    assert delete(second).status_code == 404  # 이미 삭제된 문서
    documents._index(repo, first["upload_id"])
    assert not store.chunks(where={"doc_id": "UP-MANUAL"})


def test_delete_failure_is_visible_and_retryable(env, monkeypatch):
    from weeing_weeing.rag.indexer import DocumentIndexer

    store, _ = env
    body = upload(other_pdf()).json()
    real_delete = DocumentIndexer.delete_document

    def broken(self, doc_id):
        raise TimeoutError("private backend details")

    monkeypatch.setattr(DocumentIndexer, "delete_document", broken)
    response = delete(body)
    assert response.status_code == 503
    assert "private" not in response.text
    [record] = TestClient(app).get("/documents").json()
    assert record["status"] == "delete_failed"
    assert db.get_documents().listed() == []
    assert upload(other_pdf()).status_code == 409
    assert store.chunks(where={"doc_id": "UP-MANUAL"})
    monkeypatch.setattr(DocumentIndexer, "delete_document", real_delete)
    assert delete(body).status_code == 200
    assert TestClient(app).get("/documents").json() == []
    assert not store.chunks(where={"doc_id": "UP-MANUAL"})


def test_delete_old_snapshot_does_not_remove_new_version(env):
    old = upload(other_pdf()).json()
    upload(other_pdf() + b"%new", name="manual_v2.0.pdf")
    assert delete(old).status_code == 409
    assert {c.doc_version for c in env[0].chunks(where={"doc_id": "UP-MANUAL"})} == {
        "2.0"
    }


def test_unknown_and_report_delete_are_404(env):
    repo = db.get_documents()
    report = add_legacy(repo, "REPORT", doc_type="report")
    assert delete(report.model_dump(), "REPORT").status_code == 404
    assert delete(report.model_dump(), "MISSING").status_code == 404


def add_legacy(repo, doc_id, **overrides):
    import hashlib

    from weeing_weeing.contracts import DocumentRecord
    from weeing_weeing.db.models import DocumentRow

    values = dict(
        doc_id=doc_id,
        doc_version="2.0",
        doc_type="manual",
        origin="seed",
        title="매뉴얼",
        source="manuals/BTT-MANUAL_v2.0.pdf",
        source_sha256=hashlib.sha256(MANUAL.read_bytes()).hexdigest(),
    )
    record = DocumentRecord(**{**values, **overrides})
    with repo._transaction() as session:
        session.add(DocumentRow(**record.model_dump()))
    return record


def test_original_manual_can_be_uploaded_without_a_catalog(env):
    response = upload(MANUAL.read_bytes(), doc_id="BTT-MANUAL")
    assert response.status_code == 202
    assert (
        db.get_documents().get_upload(response.json()["upload_id"]).status
        == "completed"
    )


def test_same_pdf_under_another_id_is_rejected_from_db_hash(env):
    assert upload(other_pdf()).status_code == 202
    response = upload(other_pdf(), doc_id="DUPLICATE")
    assert response.status_code == 409
    assert "같은 내용" in response.json()["detail"]


def test_deleted_legacy_manual_can_be_uploaded_again(env):
    from weeing_weeing.rag.store import Chunk

    repo = db.get_documents()
    record = add_legacy(repo, "BTT-MANUAL")
    env[0].replace_document(
        "BTT-MANUAL",
        [
            Chunk(
                "BTT-MANUAL:2.0:0000",
                "BTT-MANUAL",
                "2.0",
                "이전 검색 자료",
                {"doc_type": "manual"},
            )
        ],
    )
    assert delete(record.model_dump(), "BTT-MANUAL").status_code == 200
    assert repo.listed() == []
    assert not env[0].chunks(where={"doc_id": "BTT-MANUAL"})
    response = upload(MANUAL.read_bytes(), doc_id="BTT-MANUAL")
    assert response.status_code == 202, response.text
    assert len(repo.listed()) == 1
    assert env[0].chunks(where={"doc_id": "BTT-MANUAL"})


def test_delete_failure_can_recover_even_if_vectors_already_gone(env, monkeypatch):
    body = upload(other_pdf()).json()
    real_finish = SqlDocuments.finish_delete

    def fail_db(self, doc_id, *, error=None):
        raise db.DatabaseUnavailableError("write failed")

    monkeypatch.setattr(SqlDocuments, "finish_delete", fail_db)
    assert delete(body).status_code == 503
    assert not env[0].chunks(where={"doc_id": "UP-MANUAL"})
    # SQLite는 트랜잭션을 되돌리고 PostgreSQL은 deleting이 남는다. 양쪽 모두 재시도한다.
    monkeypatch.setattr(SqlDocuments, "finish_delete", real_finish)
    assert delete(body).status_code == 200
    assert db.get_documents().managed_documents() == []


def test_physical_delete_and_identical_reupload_with_qdrant(env, tmp_path, monkeypatch):
    from fakes import FakeEmbedder
    from qdrant_client import QdrantClient

    from weeing_weeing.rag.qdrant_store import QdrantVectorStore

    client = QdrantClient(path=str(tmp_path / "qdrant"))
    try:
        store = QdrantVectorStore(
            client, embedder=FakeEmbedder(), embedding_model="test"
        )
        monkeypatch.setattr(interface, "get_indexer", lambda: DocumentIndexer(store))
        body = upload(MANUAL.read_bytes(), doc_id="BTT-MANUAL").json()
        assert client.count("knowledge").count > 0
        assert delete(body, "BTT-MANUAL").status_code == 200
        assert client.count("knowledge").count == 0
        assert db.get_documents().get_upload(body["upload_id"]) is None
        assert db.get_documents().managed_documents() == []
        again = upload(MANUAL.read_bytes(), doc_id="BTT-MANUAL")
        assert again.status_code == 202, again.text
        assert client.count("knowledge").count > 0
        assert len(db.get_documents().managed_documents()) == 1
    finally:
        client.close()
