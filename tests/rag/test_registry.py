"""문서 레지스트리: git의 catalog.toml + git 밖 업로드 매니페스트를 하나의 목록으로."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from weeing_weeing.rag.registry import (
    load_registry,
    supersede_uploads,
    upload_conflict,
    upload_entries,
)
from weeing_weeing.rag.sync import index_metadata

DATA = Path(__file__).resolve().parents[2] / "data"
MANUAL = DATA / "manuals/BTT-MANUAL_v2.0.pdf"


def write_upload(
    upload_dir: Path,
    upload_id: str,
    *,
    doc_id="UP-1",
    status="completed",
    content=b"%PDF-1.4 a",
    version="1.0",
):
    folder = upload_dir / upload_id
    folder.mkdir(parents=True)
    (folder / "doc.pdf").write_bytes(content)
    record = {
        "upload_id": upload_id,
        "doc_id": doc_id,
        "doc_version": version,
        "doc_type": "manual",
        "doc_status": "approved",
        "asset_id": "BLDC-001",
        "title": "doc.pdf",
        "source": "doc.pdf",
        "status": status,
        "source_sha256": hashlib.sha256(content).hexdigest(),  # 업로드 API가 쓰는 값
    }
    (folder / "metadata.json").write_text(json.dumps(record), encoding="utf-8")
    return folder


@pytest.fixture
def catalog(tmp_path):
    (tmp_path / "data").mkdir()
    shutil.copy(MANUAL, tmp_path / "data/m.pdf")
    path = tmp_path / "data/catalog.toml"
    path.write_text(
        '[[documents]]\ndoc_id = "BTT-MANUAL"\ndoc_version = "2.0"\ndoc_type = "manual"\n'
        'status = "approved"\npath = "m.pdf"\ntitle = "매뉴얼"\n',
        encoding="utf-8",
    )
    return path


def test_only_completed_uploads_are_listed(tmp_path):
    uploads = tmp_path / "uploads"
    write_upload(uploads, "a", doc_id="UP-A")
    write_upload(uploads, "b", doc_id="UP-B", status="processing", content=b"b")
    write_upload(uploads, "c", doc_id="UP-C", status="superseded", content=b"c")

    assert [e.doc_id for e in upload_entries(uploads)] == ["UP-A"]
    assert upload_entries(tmp_path / "없는폴더") == []


def test_upload_entry_carries_extra_metadata(tmp_path):
    entry = upload_entries(write_upload(tmp_path / "u", "a").parent)[0]

    meta = index_metadata(entry, "sha")
    assert meta["asset_id"] == "BLDC-001"
    assert meta["upload_id"] == "a"
    assert meta["status"] == "approved"
    assert Path(meta["source_path"]).is_absolute()


def test_registry_merges_catalog_and_uploads(catalog, tmp_path):
    write_upload(tmp_path / "uploads", "a", doc_id="UP-A")

    registry = load_registry(catalog, tmp_path / "uploads")
    assert [e.doc_id for e in registry.documents] == ["BTT-MANUAL", "UP-A"]
    assert registry.file(registry.documents[1]).is_file()


def test_upload_conflict_messages(catalog, tmp_path):
    uploads = tmp_path / "uploads"
    write_upload(uploads, "a", doc_id="UP-A", content=b"aaa")
    sha_manual = hashlib.sha256(MANUAL.read_bytes()).hexdigest()
    sha_a = hashlib.sha256(b"aaa").hexdigest()

    assert "카탈로그" in upload_conflict("BTT-MANUAL", "new", catalog, uploads)
    assert "같은 내용" in upload_conflict("UP-NEW", sha_manual, catalog, uploads)
    assert "같은 내용" in upload_conflict("UP-NEW", sha_a, catalog, uploads)
    # 같은 doc_id의 새 업로드(개정판)는 허용, 같은 파일 재업로드도 같은 doc_id면 허용
    assert upload_conflict("UP-A", "new", catalog, uploads) is None
    assert upload_conflict("UP-A", sha_a, catalog, uploads) is None
    assert upload_conflict("UP-NEW", "new", catalog, uploads) is None


def test_supersede_marks_older_uploads_of_same_doc(tmp_path):
    uploads = tmp_path / "uploads"
    write_upload(uploads, "old", doc_id="UP-A", content=b"1")
    write_upload(uploads, "new", doc_id="UP-A", content=b"2", version="2.0")
    write_upload(uploads, "other", doc_id="UP-B", content=b"3")

    assert supersede_uploads(uploads, "UP-A", keep="new") == ["old"]
    assert [(e.doc_id, e.doc_version) for e in upload_entries(uploads)] == [
        ("UP-A", "2.0"),
        ("UP-B", "1.0"),
    ]


# --- 리뷰 반영: 업로드 하나가 잘못돼도 전체가 멈추지 않는다 ---


def test_malformed_manifest_is_skipped_with_warning(catalog, tmp_path):
    uploads = tmp_path / "uploads"
    write_upload(uploads, "good", doc_id="UP-A", content=b"a")
    bad = uploads / "bad"
    bad.mkdir()
    (bad / "metadata.json").write_text('{"status": "completed"}', encoding="utf-8")
    (uploads / "broken").mkdir()
    (uploads / "broken/metadata.json").write_text("{not json", encoding="utf-8")

    warnings: list[str] = []
    registry = load_registry(catalog, uploads, warnings=warnings)
    assert [e.doc_id for e in registry.documents] == ["BTT-MANUAL", "UP-A"]
    assert any("bad" in w for w in warnings)


def test_completed_upload_without_file_is_skipped(catalog, tmp_path):
    folder = write_upload(tmp_path / "uploads", "a", doc_id="UP-A")
    (folder / "doc.pdf").unlink()

    warnings: list[str] = []
    registry = load_registry(catalog, tmp_path / "uploads", warnings=warnings)
    assert [e.doc_id for e in registry.documents] == ["BTT-MANUAL"]
    assert any("파일 없음" in w for w in warnings)


def test_conflicting_uploads_are_dropped_not_fatal(catalog, tmp_path):
    uploads = tmp_path / "uploads"
    write_upload(uploads, "a", doc_id="BTT-MANUAL", content=b"x")  # 카탈로그 doc_id
    write_upload(
        uploads, "b", doc_id="UP-B", content=MANUAL.read_bytes()
    )  # 카탈로그와 같은 내용
    write_upload(uploads, "c", doc_id="UP-C", content=b"same")
    write_upload(uploads, "d", doc_id="UP-D", content=b"same")  # 앞 업로드와 같은 내용

    warnings: list[str] = []
    registry = load_registry(catalog, uploads, warnings=warnings)
    assert [e.doc_id for e in registry.documents] == ["BTT-MANUAL", "UP-C"]
    assert len(warnings) == 3


def test_newest_completed_upload_wins_for_same_doc_id(catalog, tmp_path):
    uploads = tmp_path / "uploads"
    for upload_id, version, at in [
        ("x", "1.0", "2026-10-27T01:00"),
        ("y", "2.0", "2026-10-27T02:00"),
    ]:
        folder = write_upload(
            uploads, upload_id, doc_id="UP-A", content=version.encode(), version=version
        )
        record = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        record["uploaded_at"] = at
        (folder / "metadata.json").write_text(json.dumps(record), encoding="utf-8")

    registry = load_registry(catalog, uploads)
    assert [(e.doc_id, e.doc_version) for e in registry.documents][1:] == [
        ("UP-A", "2.0")
    ]


def test_conflict_check_includes_in_progress_uploads(catalog, tmp_path):
    uploads = tmp_path / "uploads"
    folder = write_upload(
        uploads, "p", doc_id="UP-P", status="processing", content=b"zz"
    )
    record = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    record["source_sha256"] = "sha-zz"
    (folder / "metadata.json").write_text(json.dumps(record), encoding="utf-8")

    assert "같은 내용" in upload_conflict("UP-NEW", "sha-zz", catalog, uploads)


def test_newer_upload_lookup(tmp_path):
    from weeing_weeing.rag.registry import newer_upload

    uploads = tmp_path / "uploads"
    for upload_id, at, status in [
        ("old", "2026-10-27T01:00", "queued"),
        ("new", "2026-10-27T02:00", "processing"),
    ]:
        folder = write_upload(
            uploads, upload_id, doc_id="UP-A", status=status, content=at.encode()
        )
        record = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        record["uploaded_at"] = at
        (folder / "metadata.json").write_text(json.dumps(record), encoding="utf-8")

    assert newer_upload(uploads, "UP-A", "2026-10-27T01:00", exclude="old") == "new"
    assert newer_upload(uploads, "UP-A", "2026-10-27T02:00", exclude="new") is None


@pytest.mark.parametrize(
    "key", ["codes", "citation", "chunk_total", "doc_id", "status"]
)
def test_extra_cannot_use_reserved_keys(key):
    from pydantic import ValidationError

    from weeing_weeing.rag.catalog import CatalogEntry

    with pytest.raises(ValidationError, match="extra"):
        CatalogEntry(
            doc_id="A",
            doc_version="1",
            doc_type="manual",
            status="approved",
            path="a.pdf",
            title="a",
            extra={key: "x"},
        )
