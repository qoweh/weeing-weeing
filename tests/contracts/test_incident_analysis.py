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


def test_check_citations_and_unverified_draft_are_validated():
    result = make_analysis(
        status="VERIFICATION_FAILED",
        recommended_checks=["센서 앞 상태 확인"],
        check_citations=[{"check_index": 0, "evidence_ids": [EVIDENCE.evidence_id]}],
    )
    assert result.suspected_causes and result.check_citations
    for citations in (
        [{"check_index": 1, "evidence_ids": [EVIDENCE.evidence_id]}],
        [{"check_index": 0, "evidence_ids": ["unknown"]}],
        [{"check_index": 0, "evidence_ids": [EVIDENCE.evidence_id]}] * 2,
    ):
        with pytest.raises(ValidationError):
            make_analysis(recommended_checks=["점검"], check_citations=citations)


def test_action_citations_and_candidate_details_round_trip():
    result = make_analysis(
        recommended_actions=["담당자에게 점검 요청"],
        action_citations=[{"action_index": 0, "evidence_ids": [EVIDENCE.evidence_id]}],
        actions_requiring_approval=["승인 후 재가동 판단"],
        approval_citations=[
            {"action_index": 0, "evidence_ids": [EVIDENCE.evidence_id]}
        ],
    )
    result.suspected_causes[0].unconfirmed = ["현장 점검 결과"]
    result.suspected_causes[0].observations = ["검증된 관측"]
    assert AnalysisResult.model_validate_json(result.model_dump_json()) == result
    for field in ("action_citations", "approval_citations"):
        for citations in (
            [{"action_index": 1, "evidence_ids": [EVIDENCE.evidence_id]}],
            [{"action_index": 0, "evidence_ids": ["unknown"]}],
            [{"action_index": 0, "evidence_ids": [EVIDENCE.evidence_id]}] * 2,
        ):
            data = result.model_dump()
            data[field] = citations
            with pytest.raises(ValidationError):
                AnalysisResult.model_validate(data)


def test_incident_number_is_optional_and_round_trips():
    incident = make_incident()
    assert incident.incident_number is None
    numbered = incident.model_copy(
        update={"incident_number": "INC-BTT2-P03-20261005-001"}
    )
    assert Incident.model_validate_json(numbered.model_dump_json()) == numbered


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


def test_reference_cases_require_known_single_report_and_unique_bounded_cases():
    case = dict(
        symptom="고온",
        action="팬 청소",
        outcome="온도 회복",
        similarity="고온 증상",
        differences="현장 확인 필요",
        evidence_ids=[EVIDENCE.evidence_id],
    )
    assert make_analysis().reference_cases == []
    result = make_analysis(reference_cases=[case])
    assert AnalysisResult.model_validate_json(result.model_dump_json()) == result
    other = EVIDENCE.model_copy(update={"evidence_id": "other", "doc_id": "RPT-other"})
    for cases in (
        [dict(case, evidence_ids=["invented"])],
        [dict(case, evidence_ids=[EVIDENCE.evidence_id, "other"])],
        [case, case],
        [case] * 3,
    ):
        with pytest.raises(ValidationError):
            make_analysis(evidence=[EVIDENCE, other], reference_cases=cases)


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


def test_unevaluated_candidate_still_requires_real_citation():
    candidate = CauseCandidate(
        cause="냉각 상태 점검",
        likelihood="미평가",
        basis="점검 결과 없음",
        evidence_ids=[EVIDENCE.evidence_id],
    )
    analysis = make_analysis(suspected_causes=[candidate])
    assert AnalysisResult.model_validate_json(analysis.model_dump_json()) == analysis
    with pytest.raises(ValidationError):
        make_analysis(evidence=[], suspected_causes=[candidate])


def test_incident_can_preserve_declared_provenance():
    item = make_incident(
        telemetry_provenance={"origin": "SIMULATION", "expected_interval_s": 1}
    )
    assert Incident.model_validate_json(item.model_dump_json()) == item
    assert make_incident().telemetry_provenance is None


@pytest.mark.parametrize("page", [0, -1, True, "8", 1.5])
def test_evidence_page_rejects_non_pdf_page_values(page):
    with pytest.raises(ValidationError):
        Evidence(**{**EVIDENCE.model_dump(), "page": page})


def test_evidence_title_and_pdf_page_are_optional_for_legacy_snapshots():
    old = EVIDENCE.model_dump(exclude={"page", "title"})
    assert Evidence.model_validate(old).page is None
    new = Evidence(**{**old, "page": 8, "title": "이송 설비 매뉴얼"})
    assert Evidence.model_validate_json(new.model_dump_json()) == new


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


def test_evidence_relevance_is_optional_and_preserves_rrf_in_json():
    # 기존 저장 JSON은 새 필드가 없어도 읽는다. None은 측정된 0점과 다르다.
    legacy = EVIDENCE.model_dump(exclude={"relevance"})
    assert Evidence.model_validate(legacy).relevance is None
    for relevance in (0.0, 0.9, -2.0):
        evidence = Evidence(**legacy, relevance=relevance).model_copy(
            update={"score": 0.03}
        )
        result = make_analysis(evidence=[evidence])
        restored = AnalysisResult.model_validate_json(result.model_dump_json())
        assert restored.evidence[0].relevance == relevance
        assert restored.evidence[0].score == 0.03


@pytest.mark.parametrize("relevance", [float("nan"), float("inf"), -float("inf")])
def test_evidence_rejects_nonfinite_relevance(relevance):
    with pytest.raises(ValidationError):
        Evidence(**EVIDENCE.model_dump(exclude={"relevance"}), relevance=relevance)


@pytest.mark.parametrize("priority", ["우선 확인", "후속 확인"])
def test_inspection_priority_round_trip_without_legacy_likelihood(priority):
    candidate = CauseCandidate(
        cause="감지면 오염",
        inspection_priority=priority,
        priority_reason="해당 코드의 매뉴얼이 감지면 확인을 먼저 안내한다.",
        basis="문서에 오염 점검 절차가 있다.",
        evidence_ids=[EVIDENCE.evidence_id],
    )
    result = make_analysis(suspected_causes=[candidate])
    restored = AnalysisResult.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.suspected_causes[0].likelihood is None
    with pytest.raises(ValidationError):
        make_analysis(suspected_causes=[candidate], evidence=[])


@pytest.mark.parametrize("legacy", ["상", "중", "하", "미평가"])
def test_legacy_likelihood_never_becomes_inspection_priority(legacy):
    old = {"cause": "오염", "likelihood": legacy, "basis": "기존 근거"}
    candidate = CauseCandidate.model_validate(old)
    assert candidate.likelihood == legacy
    assert candidate.inspection_priority is None
    assert candidate.priority_reason is None


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"inspection_priority": "상", "priority_reason": "이유"},
        {"inspection_priority": "우선 확인"},
        {"inspection_priority": "후속 확인", "priority_reason": "   "},
        {"priority_reason": "등급에서 추측한 순서"},
    ],
)
def test_priority_rejects_unknown_levels_and_missing_explanations(fields):
    with pytest.raises(ValidationError):
        CauseCandidate(cause="점검", basis="근거", **fields)
