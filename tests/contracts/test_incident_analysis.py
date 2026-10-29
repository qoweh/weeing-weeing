from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from weeing_weeing.contracts import (
    CODES,
    AnalysisResult,
    CauseCandidate,
    Evidence,
    Incident,
    MaintenanceReport,
    Severity,
)

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 10, 5, 14, 0, 23, tzinfo=KST)

EVIDENCE = Evidence(
    evidence_id="BTT-MANUAL-2.0-03-P03",
    doc_id="BTT-MANUAL",
    doc_version="2.0",
    section="03 이송·광전 현장 대응 절차",
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
                cause="입구 트레이 정체·가이드 간섭",
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


def test_code_catalog_has_31_prefixed_codes():
    # 정의서 11절: P01~P07 + M01~M19 + D01~D05
    assert len(CODES) == 31
    assert all(code.startswith("BTT2-") for code in CODES)


def test_incident_rejects_undefined_code():
    with pytest.raises(ValidationError):
        make_incident(codes=["BTT-P02"])  # 구버전 1.x 코드


def test_analysis_ok_requires_evidence():
    with pytest.raises(ValidationError):
        make_analysis(evidence=[], suspected_causes=[])


def test_analysis_rejects_citation_to_missing_evidence():
    bad = CauseCandidate(
        cause="x", likelihood="중", basis="y", evidence_ids=["NOT-RETRIEVED"]
    )
    with pytest.raises(ValidationError):
        make_analysis(suspected_causes=[bad])


def test_analysis_ok_rejects_cause_without_citation():
    # 관련 없는 근거가 하나 있어도, 인용 없는 원인 후보는 통과하면 안 된다
    uncited = CauseCandidate(cause="x", likelihood="하", basis="y", evidence_ids=[])
    with pytest.raises(ValidationError):
        make_analysis(suspected_causes=[uncited])


def test_insufficient_evidence_is_allowed_without_evidence():
    result = make_analysis(
        status="INSUFFICIENT_EVIDENCE", evidence=[], suspected_causes=[]
    )
    assert result.status == "INSUFFICIENT_EVIDENCE"


def test_report_round_trips_as_json():
    report = MaintenanceReport(
        report_id="RPT-20261005-001",
        incident_id="INC-20261005-001",
        process_id="BAT-TRANSFER-01",
        asset_id="BLDC-001",
        data_origin="SYNTHETIC",
        incident=make_incident(),
        ai_analysis=make_analysis(),
    )
    assert MaintenanceReport.model_validate_json(report.model_dump_json()) == report
