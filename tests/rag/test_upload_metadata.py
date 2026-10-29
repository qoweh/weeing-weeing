"""웹 업로드는 DB에 접수한 정보만으로 색인 메타데이터를 만든다."""

from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.rag.interface import upload_index_metadata


def test_upload_metadata_uses_db_record_and_resolves_file_path(tmp_path):
    record = DocumentRecord(
        doc_id="WEB-MANUAL",
        doc_version="1",
        doc_type="manual",
        origin="upload",
        upload_id="a" * 32,
        title="현장 매뉴얼.pdf",
        source="a/manual.pdf",
        source_sha256="sha-of-upload",
        status="queued",
        extra={"asset_id": "BLDC-001", "title": "덮어쓸 수 없음"},
    )
    metadata = upload_index_metadata(record, tmp_path)
    assert metadata == {
        "asset_id": "BLDC-001",
        "doc_id": "WEB-MANUAL",
        "doc_version": "1",
        "doc_type": "manual",
        "status": "approved",
        "title": "현장 매뉴얼.pdf",
        "source_path": str((tmp_path / "a/manual.pdf").resolve()),
        "source_sha256": "sha-of-upload",
        "upload_id": "a" * 32,
    }
