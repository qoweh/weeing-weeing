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


def history_source(**changes):
    return (
        dict(
            kind="HISTORY_QUERY",
            source_id="query:1",
            title="DB 조회",
            conditions={},
            total=0,
            synthetic_total=0,
            snapshot="a" * 64,
        )
        | changes
    )


def test_zero_history_count_has_a_valid_server_source_and_roundtrips():
    from weeing_weeing.contracts import ChatHistorySource
    from weeing_weeing.contracts.chat_tools import ChatHistoryQuery, ChatHistoryResult

    result = ChatHistoryResult(source=history_source(), truncated=False)
    assert ChatHistoryResult.model_validate_json(result.model_dump_json()) == result
    for changes in (
        dict(total=-1),
        dict(total=True),
        dict(synthetic_total=1),
        dict(snapshot="invented"),
    ):
        with pytest.raises(ValidationError):
            ChatHistorySource(**history_source(**changes))
    with pytest.raises(ValidationError):
        ChatHistoryQuery(code="made-up")
    with pytest.raises(ValidationError):
        ChatHistoryResult(source=history_source(total=1), truncated=False)
    with pytest.raises(ValidationError):
        ChatHistoryQuery(
            conditions={"date_from": "2026-10-02", "date_to": "2026-10-01"}
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"state": "ALL"},
        {"severity": "Normal"},
        {"code": "UNKNOWN"},
        {"time_from": "2026-11-02T10:00:00"},
        {
            "time_from": "2026-11-02T10:00:00+09:00",
            "time_to": "2026-11-02T09:00:00+09:00",
        },
        {"limit": True},
        {"role": "관리자"},
    ],
)
def test_incident_query_rejects_invalid_filters(bad):
    from weeing_weeing.contracts.chat import ChatIncidentQuery

    with pytest.raises(ValidationError):
        ChatIncidentQuery(**bad)


def test_incident_source_and_response_validate_counts_and_citation_kind():
    from datetime import UTC, datetime
    from uuid import uuid4

    from weeing_weeing.contracts.chat import ChatIncidentSource, ChatResponse

    source = ChatIncidentSource(
        source_id="incidents:zero",
        title="현재 알림 조회",
        query={},
        total=0,
        warning_count=0,
        error_count=0,
        retrieved_at=datetime.now(UTC),
    )
    response = ChatResponse(
        request_id=uuid4(),
        intent="INCIDENT",
        status="OK",
        applied_conditions={},
        message="조회 결과",
        parts=[
            dict(
                kind="INCIDENT",
                text="조회 시점에 진행 중인 알림은 0건입니다.",
                source_ids=[source.source_id],
            )
        ],
        sources=[source],
        generated_at=datetime.now(UTC),
    )
    assert ChatResponse.model_validate_json(response.model_dump_json()) == response
    with pytest.raises(ValidationError):
        ChatIncidentSource.model_validate(source.model_dump() | {"total": 1})
    bad = response.model_dump()
    bad["parts"][0]["kind"] = "MANUAL"
    with pytest.raises(ValidationError):
        ChatResponse.model_validate(bad)
