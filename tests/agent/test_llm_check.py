"""구조화 출력 점검(make llm-check): 스키마 제약, 계약 검증, 보고서, 종료 코드. 가짜 LLM으로."""

import importlib.util
import json
from pathlib import Path

import pytest

from weeing_weeing.agent.interface import (
    LlmModelMissingError,
    LlmTimeoutError,
    LlmUnavailableError,
)
from weeing_weeing.agent.llm_check import (
    CheckCase,
    check_case,
    draft_schema,
    format_markdown,
    load_cases,
    run_check,
    user_prompt,
)

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "data/eval/llm_cases_v1.toml"

EVIDENCE = {
    "evidence_id": "BTT-MANUAL:2.0:0007",
    "doc_id": "BTT-MANUAL",
    "doc_version": "2.0",
    "citation": "BTT-MANUAL 2.0 3절",
    "text": "센서 감지면 오염을 확인한다.",
}
CASE = CheckCase(
    id="c", incident="P03 입구 점유", expected_status="OK", evidence=[EVIDENCE]
)


def answer(status="OK", cited=("BTT-MANUAL:2.0:0007",)):
    causes = (
        [
            {
                "cause": "감지면 오염",
                "likelihood": "중",
                "basis": "입구 센서 연속 true",
                "evidence_ids": list(cited),
            }
        ]
        if status == "OK"
        else []
    )
    return json.dumps(
        {
            "observed_facts": "입구 점유 6초",
            "suspected_causes": causes,
            "status": status,
        }
    )


class FakeLlm:
    provider = "fake"
    model_name = "llm"
    last_usage = None

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def generate_json(self, system, user, *, timeout_s, schema=None):
        self.calls.append({"user": user, "schema": schema})
        reply = self.answers.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_sample_cases_load_and_cover_both_statuses():
    cases = load_cases(CASES)
    assert len(cases) >= 4
    assert {c.expected_status for c in cases} == {"OK", "INSUFFICIENT_EVIDENCE"}
    assert any(not c.evidence for c in cases)  # 근거 없는 사례 포함


def test_schema_requires_cited_ids_from_given_evidence():
    schema = draft_schema(["A:1:0001", "B:1:0002"])
    cause = schema["$defs"]["CauseCandidate"]
    assert "evidence_ids" in cause["required"]
    ids = cause["properties"]["evidence_ids"]
    assert ids["items"]["enum"] == ["A:1:0001", "B:1:0002"]
    assert schema["required"] == list(schema["properties"])
    assert schema["required"][-1] == "status"  # 판단은 마지막에
    assert cause["required"] == list(cause["properties"])


def test_cause_without_evidence_is_invalid_even_if_api_ignores_min_items():
    # minItems는 API가 강제하지 않으므로 check_draft가 잡아야 한다
    result = check_case(FakeLlm(answer(cited=())), CASE, timeout_s=5)
    assert not result.valid
    assert "근거를 인용하지 않은" in result.error


def test_prompt_lists_evidence_or_says_none():
    assert "[BTT-MANUAL:2.0:0007]" in user_prompt(CASE)
    empty = CASE.model_copy(update={"evidence": []})
    assert "근거 없음" in user_prompt(empty)


def test_valid_answer_becomes_analysis_result():
    llm = FakeLlm(answer())
    result = check_case(llm, CASE, timeout_s=5)
    assert result.valid and result.status_match
    assert result.result.model == "fake/llm"
    assert result.result.evidence[0].evidence_id == "BTT-MANUAL:2.0:0007"
    assert llm.calls[0]["schema"]["$defs"]["CauseCandidate"]


@pytest.mark.parametrize(
    "reply",
    [
        "{not json",
        json.dumps({"status": "OK"}),  # 필수 칸 없음
        answer(cited=("없는:근거:0001",)),  # 계약: 없는 근거 인용
        answer(cited=()),  # 계약: OK인데 인용 없음
    ],
)
def test_invalid_answers_are_reported_not_raised(reply):
    result = check_case(FakeLlm(reply), CASE, timeout_s=5)
    assert not result.valid
    assert result.error


def test_status_mismatch_is_counted_but_still_valid():
    result = check_case(FakeLlm(answer("INSUFFICIENT_EVIDENCE")), CASE, timeout_s=5)
    assert result.valid and not result.status_match


@pytest.mark.parametrize(
    "error", [LlmUnavailableError("down"), LlmModelMissingError("no model")]
)
def test_server_or_model_missing_stops_the_check(error):
    with pytest.raises(type(error)):
        check_case(FakeLlm(error), CASE, timeout_s=5)


def test_timeout_in_one_case_is_recorded_and_run_continues():
    report = run_check(
        FakeLlm(LlmTimeoutError("60초 안에 응답 없음"), answer()),
        [CASE, CASE],
        timeout_s=5,
    )
    assert [r.valid for r in report.results] == [False, True]
    assert "LlmTimeoutError" in report.results[0].error


def test_insufficient_with_causes_is_invalid():
    reply = json.loads(answer())
    reply["status"] = "INSUFFICIENT_EVIDENCE"
    result = check_case(FakeLlm(json.dumps(reply)), CASE, timeout_s=5)
    assert not result.valid
    assert "원인 후보" in result.error


def test_report_summarizes_runs():
    report = run_check(FakeLlm(answer(), "{bad"), [CASE], timeout_s=5, repeat=2)
    assert not report.ok
    text = format_markdown(report)
    assert "스키마·계약 통과: **1/2**" in text
    assert "## 출력 예시" in text


# --- scripts/check_llm.py ---


def _script():
    spec = importlib.util.spec_from_file_location(
        "check_llm", ROOT / "scripts/check_llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("answers", "code"), [((answer(),), 0), (("{bad",), 1)])
def test_cli_exit_codes(monkeypatch, tmp_path, answers, code):
    script = _script()
    cases = tmp_path / "cases.toml"
    cases.write_text(
        '[[cases]]\nid = "c"\nincident = "P03"\nexpected_status = "OK"\n'
        "[[cases.evidence]]\n" + "".join(f'{k} = "{v}"\n' for k, v in EVIDENCE.items()),
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "get_llm_client", lambda settings: FakeLlm(*answers))
    out = tmp_path / "report.md"
    assert script.main(["--cases", str(cases), "--out", str(out)]) == code
    assert out.is_file()


def test_cli_cannot_start_without_server(monkeypatch, capsys):
    script = _script()

    def down(settings):
        return FakeLlm(LlmUnavailableError("Claude API에 연결하지 못함"))

    monkeypatch.setattr(script, "get_llm_client", down)
    assert script.main([]) == 2
    assert "연결하지 못함" in capsys.readouterr().err


def test_cli_model_option_overrides_setting(monkeypatch, tmp_path):
    script = _script()
    seen = {}

    def capture(settings):
        seen["model"], seen["effort"] = settings.llm_model, settings.llm_effort
        return FakeLlm(LlmUnavailableError("stop"))

    monkeypatch.setattr(script, "get_llm_client", capture)
    script.main(["--model", "claude-sonnet-5-5", "--effort", "low"])
    assert seen == {"model": "claude-sonnet-5-5", "effort": "low"}


def test_cli_rejects_zero_repeat_and_empty_cases(tmp_path, monkeypatch):
    script = _script()
    with pytest.raises(SystemExit) as info:
        script.main(["--repeat", "0"])
    assert info.value.code == 2
    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(script, "get_llm_client", lambda settings: FakeLlm())
    assert script.main(["--cases", str(empty)]) == 2
