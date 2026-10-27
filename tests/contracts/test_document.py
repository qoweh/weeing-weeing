"""DocumentRecord: db·rag·api가 주고받는 문서 레지스트리 한 줄."""

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import DocumentRecord

BASE = dict(
    doc_id="BTT-MANUAL",
    doc_version="2.0",
    doc_type="manual",
    origin="seed",
    title="매뉴얼",
    source="manuals/BTT-MANUAL_v2.0.pdf",
    source_sha256="0" * 64,
)


def test_seed_defaults_to_completed_and_approved():
    record = DocumentRecord(**BASE)
    assert record.status == "completed"
    assert record.doc_status == "approved"
    assert record.upload_id is None
    assert record.extra == {}


def test_upload_requires_upload_id():
    with pytest.raises(ValidationError, match="upload_id"):
        DocumentRecord(**{**BASE, "origin": "upload"})
    assert DocumentRecord(**{**BASE, "origin": "upload", "upload_id": "a" * 32})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("doc_id", "A:B"),  # 청크 ID 구분자
        ("doc_version", "1 0"),
        ("doc_type", "regulation"),
        ("origin", "catalog"),
        ("status", "done"),
        ("doc_status", "final"),
        ("title", ""),
    ],
)
def test_invalid_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        DocumentRecord(**{**BASE, field: value})


def test_record_is_immutable():
    record = DocumentRecord(**BASE)
    with pytest.raises(ValidationError):
        record.status = "failed"
