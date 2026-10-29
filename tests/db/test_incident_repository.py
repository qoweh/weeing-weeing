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
    incidents.save_incident(incident)

    assert incidents.get_incident(incident.incident_id) == incident
    assert incidents.get_incident("INC-없음") is None


def test_same_id_updates_instead_of_duplicating(incidents):
    incidents.save_incident(make_incident())
    recovered = make_incident(
        status=IncidentStatus.RECOVERED,
        last_detected_at=T0 + timedelta(seconds=40),
        recovered_at=T0 + timedelta(seconds=41),
    )
    incidents.save_incident(recovered)

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
    incidents.save_incident(recovered)
    incidents.save_incident(make_incident())  # 재전송된 옛 OPEN

    assert incidents.get_incident(recovered.incident_id) == recovered


def test_concurrent_first_saves_do_not_conflict(incidents):
    from concurrent.futures import ThreadPoolExecutor

    versions = [
        make_incident(last_detected_at=T0 + timedelta(seconds=s)) for s in range(16)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(incidents.save_incident, versions))

    assert incidents.get_incident(versions[0].incident_id) == versions[-1]
