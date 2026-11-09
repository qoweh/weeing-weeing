import pytest
from pydantic import ValidationError

from weeing_weeing.contracts.analysis_workflow import (
    AnalysisAgentRun,
    AnalysisCheckpoint,
    VerificationResult,
)


def test_skip_is_distinct_from_verification_pass():
    run = AnalysisAgentRun(role="verification", status="SKIPPED")
    assert run.verification is None
    assert AnalysisAgentRun.model_validate_json(run.model_dump_json()) == run


def test_research_cannot_cite_missing_evidence():
    with pytest.raises(ValidationError, match="확보하지 않은"):
        AnalysisAgentRun(
            role="documents",
            status="COMPLETED",
            research={
                "findings": [{"statement": "주장", "evidence_ids": ["invented"]}],
                "limitations": [],
            },
        )


def test_research_reference_cases_are_only_allowed_for_reports_with_real_sources():
    from weeing_weeing.contracts import Evidence

    source = Evidence(
        evidence_id="report:1",
        doc_id="RPT-1",
        doc_version="1",
        text="팬 청소로 회복",
        citation="보고서",
    )
    case = dict(
        symptom="고온",
        action="청소",
        outcome="회복",
        similarity="고온",
        differences="현장 확인",
        evidence_ids=[source.evidence_id],
    )
    data = dict(
        status="COMPLETED", research={"reference_cases": [case]}, evidence=[source]
    )
    valid = AnalysisAgentRun(role="reports", **data)
    assert AnalysisAgentRun.model_validate_json(valid.model_dump_json()) == valid
    with pytest.raises(ValidationError, match="정비이력"):
        AnalysisAgentRun(role="documents", **data)
    with pytest.raises(ValidationError, match="확보하지 않은"):
        AnalysisAgentRun(role="reports", **(data | {"evidence": []}))


def test_revision_needs_an_actionable_issue():
    with pytest.raises(ValidationError, match="구체적인 지적"):
        VerificationResult(verdict="REVISE", summary="고쳐라", issues=[])


def test_pass_cannot_hide_issues():
    with pytest.raises(ValidationError):
        VerificationResult(
            verdict="PASS",
            summary="통과",
            issues=[{"claim": "확정", "reason": "근거 없음", "correction": "수정"}],
        )


def test_stage_does_not_accept_internal_messages():
    with pytest.raises(ValidationError):
        AnalysisAgentRun(role="documents", status="RUNNING", messages=["internal"])


def test_checkpoint_rejects_missing_completed_output_and_duplicate_steps():
    with pytest.raises(ValidationError, match="재개 입력"):
        AnalysisCheckpoint(
            incident_id="INC",
            verification_enabled=True,
            runs=[
                AnalysisAgentRun(role="synthesis", status="COMPLETED"),
            ],
        )
    run = AnalysisAgentRun(role="documents", status="COMPLETED", research={})
    with pytest.raises(ValidationError, match="중복"):
        AnalysisCheckpoint(
            incident_id="INC", verification_enabled=True, runs=[run, run]
        )


def test_checkpoint_retains_empty_success_and_forbids_internal_messages():
    checkpoint = AnalysisCheckpoint(
        incident_id="INC",
        verification_enabled=False,
        runs=[AnalysisAgentRun(role="reports", status="COMPLETED", research={})],
    )
    assert (
        AnalysisCheckpoint.model_validate_json(checkpoint.model_dump_json())
        == checkpoint
    )
    with pytest.raises(ValidationError):
        AnalysisCheckpoint(**checkpoint.model_dump(), messages=["hidden"])


def test_caution_requires_and_preserves_specific_issues():
    with pytest.raises(ValidationError, match="구체적인 지적"):
        VerificationResult(verdict="CAUTION", summary="확인", issues=[])
    result = VerificationResult(
        verdict="CAUTION",
        summary="주의사항",
        issues=[{"claim": "설명", "reason": "표현 확인", "correction": "범위 확인"}],
    )
    assert VerificationResult.model_validate_json(result.model_dump_json()) == result
