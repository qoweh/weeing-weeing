"""문서 레지스트리 ↔ 색인 목록: catalog.toml → seed 행, DB 행 → Catalog."""

import hashlib
import shutil
from pathlib import Path

import pytest

from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.rag import interface
from weeing_weeing.rag.catalog import CatalogError
from weeing_weeing.rag.registry import (
    catalog_from_records,
    entry_from_record,
    seed_records,
)
from weeing_weeing.rag.sync import index_metadata

DATA = Path(__file__).resolve().parents[2] / "data"
MANUAL = DATA / "manuals/BTT-MANUAL_v2.0.pdf"


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


def write_upload(uploads: Path, upload_id: str, *, doc_id="UP-1", content=b"%PDF a"):
    folder = uploads / upload_id
    folder.mkdir(parents=True)
    (folder / "doc.pdf").write_bytes(content)
    return DocumentRecord(
        doc_id=doc_id,
        doc_version="1.0",
        doc_type="manual",
        origin="upload",
        upload_id=upload_id,
        title="doc.pdf",
        source=f"{upload_id}/doc.pdf",
        source_sha256=hashlib.sha256(content).hexdigest(),
        extra={"asset_id": "BLDC-001"},
    )


def build(records, catalog, tmp_path, warnings=None):
    return catalog_from_records(
        records,
        seed_root=catalog.parent,
        upload_dir=tmp_path / "uploads",
        warnings=warnings,
    )


def test_seed_records_from_catalog(catalog):
    [record] = seed_records(catalog)
    assert (record.doc_id, record.origin, record.status) == (
        "BTT-MANUAL",
        "seed",
        "completed",
    )
    assert record.source == "m.pdf"  # catalog.toml 폴더 기준 그대로
    assert record.source_sha256 == hashlib.sha256(MANUAL.read_bytes()).hexdigest()


def test_broken_catalog_stops(tmp_path):
    bad = tmp_path / "catalog.toml"
    bad.write_text('[[documents]]\ndoc_id = "X"\n', encoding="utf-8")
    with pytest.raises(CatalogError):
        seed_records(bad)


def test_catalog_merges_seed_and_uploads(catalog, tmp_path):
    up = write_upload(tmp_path / "uploads", "a", doc_id="UP-A")

    result = build([up, *seed_records(catalog)], catalog, tmp_path)
    assert [e.doc_id for e in result.documents] == ["BTT-MANUAL", "UP-A"]
    assert result.file(result.documents[0]) == catalog.parent / "m.pdf"
    assert result.file(result.documents[1]).is_file()


def test_upload_entry_carries_extra_metadata(tmp_path):
    record = write_upload(tmp_path / "uploads", "a")

    meta = index_metadata(entry_from_record(record, tmp_path / "uploads"), "sha")
    assert meta["asset_id"] == "BLDC-001"
    assert meta["upload_id"] == "a"
    assert meta["status"] == "approved"
    assert Path(meta["source_path"]).is_absolute()


def test_upload_index_metadata_matches_make_index(catalog, tmp_path):
    """업로드 때 넣는 값 = make index가 계산하는 값(그래야 재색인되지 않는다)."""
    from weeing_weeing.rag.sync import index_metadata as expected

    record = write_upload(tmp_path / "uploads", "a")
    entry = build([record], catalog, tmp_path).documents[0]
    assert interface.upload_index_metadata(record, tmp_path / "uploads") == expected(
        entry, record.source_sha256
    )


def test_upload_without_file_is_skipped(catalog, tmp_path):
    record = write_upload(tmp_path / "uploads", "a", doc_id="UP-A")
    (tmp_path / "uploads/a/doc.pdf").unlink()

    warnings: list[str] = []
    result = build([*seed_records(catalog), record], catalog, tmp_path, warnings)
    assert [e.doc_id for e in result.documents] == ["BTT-MANUAL"]
    assert any("파일 없음" in w for w in warnings)


def test_conflicting_uploads_are_dropped_not_fatal(catalog, tmp_path):
    uploads = tmp_path / "uploads"
    records = [
        *seed_records(catalog),
        write_upload(
            uploads, "a", doc_id="BTT-MANUAL", content=b"x"
        ),  # 카탈로그 doc_id
        write_upload(uploads, "b", doc_id="UP-B", content=MANUAL.read_bytes()),
        write_upload(uploads, "c", doc_id="UP-C", content=b"same"),
        write_upload(
            uploads, "d", doc_id="UP-D", content=b"same"
        ),  # 앞 업로드와 같은 내용
    ]

    warnings: list[str] = []
    result = build(records, catalog, tmp_path, warnings)
    assert [e.doc_id for e in result.documents] == ["BTT-MANUAL", "UP-C"]
    assert len(warnings) == 3


def test_invalid_record_is_skipped_with_warning(catalog, tmp_path):
    record = write_upload(tmp_path / "uploads", "a").model_copy(
        update={"extra": {"codes": "x"}}  # 예약 키
    )
    warnings: list[str] = []
    assert build([record], catalog, tmp_path, warnings).documents == []
    assert "값이 잘못돼" in warnings[0]


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
