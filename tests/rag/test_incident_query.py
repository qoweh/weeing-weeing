"""Incident → 검색 질의문 (#8). 형식 근거는 rag/query.py 주석(실측)."""

from datetime import UTC, datetime

from weeing_weeing.contracts import Incident, Severity
from weeing_weeing.rag import interface
from weeing_weeing.rag.query import codes_query

T = datetime(2026, 10, 27, tzinfo=UTC)


def incident(*codes):
    return Incident(
        incident_id="INC-1",
        process_id="BTT",
        asset_id="BLDC-001",
        codes=list(codes),
        severity=Severity.ERROR,
        first_detected_at=T,
        last_detected_at=T,
    )


def test_query_has_short_code_name_and_intent():
    query = interface.incident_query(incident("BTT2-P03"))
    assert query == "P03 입구 장기 점유 발생 시 원인 점검과 현장 대응 절차"
    assert "BTT2-" not in query  # 전체 코드는 코드 목록 표로 끌려가서 뺀다


def test_multiple_codes_keep_order_without_duplicates():
    query = interface.incident_query(incident("BTT2-M12", "BTT2-P03", "BTT2-M12"))
    assert query.startswith("M12 DE 진동 RMS 상한 이탈 P03 입구 장기 점유")
    assert query.count("M12") == 1
    assert query.endswith("현장 대응 절차")


def test_unknown_code_keeps_short_code():
    assert codes_query(["BTT2-Z99"]).startswith("Z99 발생 시")
