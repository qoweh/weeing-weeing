"""#106 정답 인용·상태 판정·보고서와 고정 평가셋 출처 검증."""

import hashlib
import json
from pathlib import Path

import pytest
from test_llm_check import CASE, EVIDENCE, FakeLlm, answer

from weeing_weeing.agent.errors import LlmRequestError, LlmTimeoutError, LlmUsage
from weeing_weeing.agent.llm_check import (
    CheckReport,
    check_case,
    load_cases,
    report_data,
    run_check,
)

ROOT = Path(__file__).resolve().parents[2]


def test_expected_status_mismatch_is_not_report_success():
    report = run_check(FakeLlm(answer("INSUFFICIENT_EVIDENCE")), [CASE], timeout_s=5)
    assert report.results[0].valid
    assert not report.ok and not report.results[0].passed
    assert not CheckReport("empty").ok


def test_valid_but_distractor_citation_fails_quality():
    other = dict(EVIDENCE, evidence_id="distractor")
    case = CASE.model_copy(
        update={
            "evidence": [*CASE.evidence, type(CASE.evidence[0])(**other)],
            "expected_evidence_ids": [EVIDENCE["evidence_id"]],
        }
    )
    result = check_case(FakeLlm(answer(cited=("distractor",))), case, timeout_s=5)
    assert result.valid and result.status_match and not result.citation_match
    assert not result.passed


def test_stale_usage_is_not_attached_to_failed_case():
    client = FakeLlm(LlmTimeoutError("timeout"))
    client.last_usage = LlmUsage(999, 888, 1)
    assert check_case(client, CASE, timeout_s=5).usage is None


def test_partial_report_and_percentiles():
    report = run_check(FakeLlm(answer(), answer()), [CASE], timeout_s=5, repeat=2)
    report.results[0].seconds, report.results[1].seconds = 1.0, 3.0
    data = report_data(report)
    assert (data["mean_seconds"], data["median_seconds"], data["p95_seconds"]) == (
        2.0,
        2.0,
        3.0,
    )
    assert "observed_facts" not in json.dumps(data)
    report.planned_runs = 3
    assert not report.ok


def test_dataset_has_8_codes_4_conditions_and_exact_source_excerpts():
    path = ROOT / "data/eval/llm_cases_v2.toml"
    cases = load_cases(path)
    source = json.loads(
        (ROOT / "data/eval/llm_cases_v2_sources.json").read_text("utf-8")
    )
    raw = (ROOT / source["source"]).read_bytes()
    original = raw.decode("utf-8").replace("\r\n", "\n")
    assert hashlib.sha256(original.encode("utf-8")).hexdigest() == source["sha256"]
    assert len(cases) == 32 and len({c.code for c in cases}) == 8
    for code in {c.code for c in cases}:
        assert {c.condition for c in cases if c.code == code} == {
            "correct",
            "mixed",
            "unrelated",
            "none",
        }
    for case in cases:
        assert all(e.text in original for e in case.evidence)
        assert case.expected_status == (
            "OK" if case.condition in ("correct", "mixed") else "INSUFFICIENT_EVIDENCE"
        )
        assert bool(case.expected_evidence_ids) == (case.expected_status == "OK")


def test_duplicate_case_id_is_invalid(tmp_path):
    case = '[[cases]]\nid="a"\nincident="x"\nexpected_status="OK"\n'
    path = tmp_path / "bad.toml"
    path.write_text(case * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="중복"):
        load_cases(path)


def test_http_error_aborts_instead_of_repeating_configuration():
    client = FakeLlm(LlmRequestError(400, parameter_hint="effort"), answer())
    with pytest.raises(LlmRequestError):
        run_check(client, [CASE], timeout_s=5, repeat=2)
    assert len(client.calls) == 1


def test_actual_response_model_is_separate_from_requested_model():
    client = FakeLlm(answer())
    client.last_response_model = "actual-model-version"
    report = run_check(client, [CASE], timeout_s=5)
    data = report_data(report)
    assert data["model"] == "llm"
    assert data["actual_models"] == {"actual-model-version": 1}
