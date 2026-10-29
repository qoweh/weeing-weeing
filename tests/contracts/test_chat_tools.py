import pytest
from pydantic import ValidationError

from weeing_weeing.contracts.chat_tools import ChatSearchHit, ChatSearchQuery


@pytest.mark.parametrize(
    "extra",
    [{"user_id": "other"}, {"allowed_doc_ids": ["private"]}, {"role": "관리자"}],
)
def test_search_query_cannot_supply_authority(extra):
    with pytest.raises(ValidationError):
        ChatSearchQuery(query="정비 사례", kind="MAINTENANCE_HISTORY", **extra)


def test_search_query_validates_dates_code_and_kind():
    query = ChatSearchQuery(
        query="P03 점검",
        kind="MANUAL",
        code="BTT2-P03",
        conditions={"asset_id": "BLDC-001", "date_from": "2026-10-01"},
    )
    assert ChatSearchQuery.model_validate_json(query.model_dump_json()) == query
    for extra in ({"kind": "EXECUTE_PLC"}, {"code": "UNKNOWN"}, {"query": " "}):
        with pytest.raises(ValidationError):
            ChatSearchQuery.model_validate(query.model_dump() | extra)


def test_hit_requires_real_document_location_or_explicit_report_origin():
    with pytest.raises(ValidationError):
        ChatSearchHit(
            text="본문",
            source=dict(
                kind="DOCUMENT",
                source_id="x",
                title="문서",
                doc_id="x",
                doc_version="1",
            ),
        )
    with pytest.raises(ValidationError):
        ChatSearchHit(
            text="본문",
            source=dict(
                kind="REPORT",
                source_id="x",
                title="보고서",
                report_id="x",
                report_version=1,
            ),
        )
