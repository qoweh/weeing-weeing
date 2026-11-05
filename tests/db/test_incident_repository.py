"""incident·analysis 테이블(#61): 저장·갱신·조회, 분석 결과는 사건에 매여 여러 건 쌓인다."""

from datetime import datetime, timedelta, timezone

import pytest

from weeing_weeing.contracts import (
    AnalysisResult,
    CauseCandidate,
    Evidence,
    Incident,
    IncidentStatus,
    Severity,
)
from weeing_weeing.db.interface import UnknownIncidentError

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 10, 5, 14, 0, 23, tzinfo=KST)
EVIDENCE = Evidence(
    evidence_id="BTT-MANUAL:2.0:0003",
    doc_id="BTT-MANUAL",
    doc_version="2.0",
    text="센서 앞 물체 유무와 실제 출력 상태를 먼저 대조한다.",
    citation="BTT-MANUAL 2.0 3절 P03/P04",
)


def make_incident(**overrides) -> Incident:
    data = {
        "incident_id": "INC-20261005-001",
        "process_id": "BAT-TRANSFER-01",
        "asset_id": "BLDC-001",
        "codes": ["BTT2-P03"],
        "severity": Severity.ERROR,
        "first_detected_at": T0,
        "last_detected_at": T0 + timedelta(seconds=6),
    }
    return Incident(**(data | overrides))


def make_analysis(**overrides) -> AnalysisResult:
    data = {
        "incident_id": "INC-20261005-001",
        "status": "OK",
        "observed_facts": "운전 중 입구 센서가 20~29초 연속 감지.",
        "suspected_causes": [
            CauseCandidate(
                cause="입구 트레이 정체",
                likelihood="상",
                basis="입구 장기 점유 + 출구 미감지",
                evidence_ids=[EVIDENCE.evidence_id],
            )
        ],
        "evidence": [EVIDENCE],
        "model": "anthropic/test",
        "generated_at": T0,
    }
    return AnalysisResult(**(data | overrides))


def test_save_and_get_round_trip(incidents):
    incident = make_incident()
    incident = incidents.save_incident(incident)

    assert incidents.get_incident(incident.incident_id) == incident
    assert incidents.get_incident("INC-없음") is None


def test_same_id_updates_instead_of_duplicating(incidents):
    incidents.save_incident(make_incident())
    recovered = make_incident(
        status=IncidentStatus.RECOVERED,
        last_detected_at=T0 + timedelta(seconds=40),
        recovered_at=T0 + timedelta(seconds=41),
    )
    recovered = incidents.save_incident(recovered)

    assert incidents.list_incidents() == [recovered]
    assert incidents.list_incidents(statuses=[IncidentStatus.OPEN]) == []


def test_list_filters_and_newest_first(incidents):
    old = make_incident(incident_id="INC-1")
    new = make_incident(
        incident_id="INC-2",
        first_detected_at=T0 + timedelta(minutes=5),
        last_detected_at=T0 + timedelta(minutes=5),
    )
    other = make_incident(incident_id="INC-3", asset_id="BLDC-002")
    for incident in (old, new, other):
        incidents.save_incident(incident)

    assert [i.incident_id for i in incidents.list_incidents(asset_id="BLDC-001")] == [
        "INC-2",
        "INC-1",
    ]
    since = incidents.list_incidents(since=T0 + timedelta(minutes=1))
    assert [i.incident_id for i in since] == ["INC-2"]
    assert len(incidents.list_incidents(limit=1)) == 1


def test_analysis_needs_saved_incident(incidents):
    with pytest.raises(UnknownIncidentError):
        incidents.save_analysis(make_analysis())


def test_analyses_accumulate_and_latest_wins(incidents):
    incidents.save_incident(make_incident())
    first = make_analysis()
    second = make_analysis(
        status="INSUFFICIENT_EVIDENCE",
        suspected_causes=[],
        evidence=[],
        model="anthropic/other",
        generated_at=T0 + timedelta(minutes=1),
    )
    first_id = incidents.save_analysis(first)
    second_id = incidents.save_analysis(second)

    assert second_id > first_id
    assert incidents.latest_analysis(first.incident_id) == second
    assert incidents.list_analyses(first.incident_id) == [second, first]
    assert incidents.latest_analysis("INC-없음") is None


def test_older_update_arriving_late_is_ignored(incidents):
    recovered = make_incident(
        status=IncidentStatus.RECOVERED,
        last_detected_at=T0 + timedelta(seconds=40),
        recovered_at=T0 + timedelta(seconds=41),
    )
    recovered = incidents.save_incident(recovered)
    incidents.save_incident(make_incident())  # 재전송된 옛 OPEN

    assert incidents.get_incident(recovered.incident_id) == recovered


def test_concurrent_first_saves_do_not_conflict(incidents):
    from concurrent.futures import ThreadPoolExecutor

    versions = [
        make_incident(last_detected_at=T0 + timedelta(seconds=s)) for s in range(16)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(incidents.save_incident, versions))

    saved = incidents.get_incident(versions[0].incident_id)
    assert saved == versions[-1].model_copy(
        update={"incident_number": saved.incident_number}
    )


def test_number_sequence_is_stable_and_not_reused(incidents):
    first = incidents.save_incident(make_incident(incident_id="INC-first"))
    second = incidents.save_incident(make_incident(incident_id="INC-second"))
    assert first.incident_number == "INC-BTT2-P03-20261005-001"
    assert second.incident_number == "INC-BTT2-P03-20261005-002"
    updated = incidents.save_incident(make_incident(incident_id="INC-first"))
    assert updated.incident_number == first.incident_number
    from sqlalchemy import delete

    from weeing_weeing.db.models import IncidentRow

    with incidents._transaction() as session:
        session.execute(
            delete(IncidentRow).where(IncidentRow.incident_id == first.incident_id)
        )
    third = incidents.save_incident(make_incident(incident_id="INC-third"))
    assert third.incident_number == "INC-BTT2-P03-20261005-003"


def test_numbers_use_korea_date_and_are_unique_under_concurrency(incidents):
    from concurrent.futures import ThreadPoolExecutor

    at = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
    items = [
        make_incident(incident_id=f"INC-{i}", first_detected_at=at) for i in range(12)
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        saved = list(pool.map(incidents.save_incident, items))
    assert {item.incident_number for item in saved} == {
        f"INC-BTT2-P03-20261005-{i:03d}" for i in range(1, 13)
    }


def test_legacy_incident_gets_number_without_overwriting_newer_data(incidents):
    from sqlalchemy import update

    from weeing_weeing.db.models import IncidentRow

    original = incidents.save_incident(make_incident())
    with incidents._transaction() as session:
        row = session.get(IncidentRow, original.incident_id)
        data = dict(row.data)
        data.pop("incident_number")
        session.execute(
            update(IncidentRow)
            .where(IncidentRow.incident_id == original.incident_id)
            .values(incident_number=None, data=data)
        )
    older = make_incident(last_detected_at=T0)
    incidents.save_incident(older)
    saved = incidents.get_incident(original.incident_id)
    assert saved.last_detected_at == original.last_detected_at
    assert saved.incident_number == "INC-BTT2-P03-20261005-002"


def test_chat_alert_counts_are_full_and_filters_are_exact(incidents):
    from weeing_weeing.contracts.chat import ChatIncidentQuery

    for number in range(105):
        incidents.save_incident(
            make_incident(
                incident_id=f"INC-{number:03}",
                severity="Warning" if number < 103 else "Error",
                status="ACKNOWLEDGED" if number == 0 else "OPEN",
            )
        )
    incidents.save_incident(
        make_incident(incident_id="recovered", status="RECOVERED", recovered_at=T0)
    )
    incidents.save_incident(make_incident(incident_id="unknown", severity="Unknown"))
    result = incidents.query_incidents(ChatIncidentQuery(limit=3))
    assert (
        result.source.total,
        result.source.warning_count,
        result.source.error_count,
    ) == (105, 103, 2)
    assert len(result.incidents) == 3 and result.truncated
    filtered = incidents.query_incidents(
        ChatIncidentQuery(severity="Error", code="BTT2-P03")
    )
    assert filtered.source.total == 2
    assert (
        incidents.query_incidents(ChatIncidentQuery(code="BTT2-P04")).source.total == 0
    )
    assert (
        incidents.query_incidents(ChatIncidentQuery(asset_id="missing")).source.total
        == 0
    )


def test_latest_recovery_uses_recovery_time_not_occurrence_or_report(incidents):
    from weeing_weeing.contracts.chat import ChatIncidentQuery

    # 오래전에 발생했어도 마지막에 회복한 사건이 선택된다.
    incidents.save_incident(
        make_incident(
            incident_id="last-recovery",
            status="RECOVERED",
            recovered_at=T0 + timedelta(hours=4),
        )
    )
    incidents.save_incident(
        make_incident(
            incident_id="newer-start",
            status="CLOSED",
            first_detected_at=T0 + timedelta(hours=1),
            recovered_at=T0 + timedelta(hours=2),
        )
    )
    incidents.save_incident(make_incident(incident_id="still-active"))
    result = incidents.query_incidents(ChatIncidentQuery(state="RECOVERED"))
    assert [i.incident_id for i in result.incidents] == ["last-recovery"]
    assert (
        result.latest_recovered_only and result.truncated and result.source.total == 2
    )
    ranged = incidents.query_incidents(
        ChatIncidentQuery(
            state="RECOVERED",
            time_from=T0 + timedelta(hours=1),
            time_to=T0 + timedelta(hours=3),
        )
    )
    assert [i.incident_id for i in ranged.incidents] == ["newer-start"]
    assert not ranged.latest_recovered_only
    assert incidents.get_incident("last-recovery") is not None


def test_incident_measurements_and_thresholds_are_preserved(incidents):
    from weeing_weeing.contracts import SensorEvidence
    from weeing_weeing.contracts.chat import ChatIncidentQuery

    incidents.save_incident(
        make_incident(
            evidence=[
                SensorEvidence(
                    field="motor_housing_temp_c",
                    value=91.0,
                    unit="℃",
                    threshold=">= 90℃, 10초 지속",
                    observed="10초 초과 관측",
                )
            ]
        )
    )
    result = incidents.query_incidents(ChatIncidentQuery())
    fact = result.incidents[0].evidence[0]
    assert fact.value == 91.0 and fact.threshold == ">= 90℃, 10초 지속"
    assert "plc_context" not in result.incidents[0].model_dump()
