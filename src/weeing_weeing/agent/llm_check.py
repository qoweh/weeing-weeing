"""LLM 구조화 출력 점검 (#10에서 시작, #101에서 Claude로 전환, make llm-check).

사례(data/eval/llm_cases_v1.toml)마다 사건 설명과 근거를 주고, 모델이 JSON 스키마대로
분석 초안을 내는지 확인한다. 모델·effort 비교에 같은 사례를 쓴다. 검색은 하지 않는다
(근거를 고정해 LLM 판단만 잰다). 검색까지 포함한 실행은 make analyze(analyst.py).

    반드시 통과: JSON 파싱 → AnalysisDraft 스키마 → 제출 검사(check_draft) → AnalysisResult 계약
    숫자로 기록: 기대 상태(OK / INSUFFICIENT_EVIDENCE) 일치율, 응답 시간, 토큰 수
"""

import json
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from statistics import fmean, median
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from weeing_weeing.agent.analyst import AnalysisDraft, check_draft
from weeing_weeing.agent.errors import (
    LlmError,
    LlmModelMissingError,
    LlmRequestError,
    LlmUnavailableError,
    LlmUsage,
)
from weeing_weeing.contracts import AnalysisResult, Evidence

PROMPT_VERSION = "llm-check-v5"

SYSTEM = """너는 배터리 트레이 이송 설비의 정비 보조 AI다. 한국어로 답한다.
할 일: 사건과 근거(evidence)를 읽고, 근거에 적힌 내용으로 원인 후보와 점검 순서를 제안한다.

규칙:
1. 근거에 있는 내용만 쓴다. 근거에 없는 원인·수치·절차를 지어내지 않는다.
2. 근거가 사건의 코드나 현상(예: 같은 룰 코드, 같은 센서·증상)을 다루면,
   그 근거에 적힌 점검 대상을 원인 후보로 제시하고 status는 OK로 한다.
   원인 후보는 "가능성"을 제시하는 것이지 원인을 확정하는 것이 아니다.
   inspection_priority(우선 확인·후속 확인)와 priority_reason으로 점검 순서와 근거를 제시한다.
   공식 안전·점검 순서를 우선하며 현재 현장 점검 결과가 없다고 후보를 포기하지 않는다. 발생 확률·원인 확정으로 표현하지 않는다.
3. 원인 후보마다 그 내용을 담은 근거의 evidence_id를 evidence_ids에 넣는다.
   목록에 없는 ID는 쓰지 않는다.
   basis에는 그 후보를 뒷받침하는 사건의 센서 관측을 요약한다(근거 ID를 적지 않는다).
4. 근거가 없거나, 있어도 사건의 코드·현상과 관련이 없으면 status는 INSUFFICIENT_EVIDENCE다.
   이때 suspected_causes는 비우고 additional_checks에 더 확인할 것을 쓴다.
5. 정지 해제·재가동·부품 교체처럼 사람의 승인이 필요한 조치는 actions_requiring_approval에 넣는다.
6. 지정한 JSON 형식으로만 답한다. status는 다른 칸을 모두 쓴 뒤 마지막에 정한다."""


class CheckCase(BaseModel):
    id: str
    incident: str
    expected_status: Literal["OK", "INSUFFICIENT_EVIDENCE"]
    evidence: list[Evidence] = Field(default_factory=list)
    code: str | None = None
    condition: Literal["correct", "mixed", "unrelated", "none"] | None = None
    expected_evidence_ids: list[str] | None = None

    @model_validator(mode="after")
    def known_expected_sources(self):
        if len({e.evidence_id for e in self.evidence}) != len(self.evidence):
            raise ValueError("사례 안에 중복 근거 ID")
        if self.expected_evidence_ids is not None:
            known = {e.evidence_id for e in self.evidence}
            if set(self.expected_evidence_ids) - known:
                raise ValueError("정답 근거 ID가 제공 근거에 없다")
            if self.expected_status == "OK" and not self.expected_evidence_ids:
                raise ValueError("OK 사례에는 정답 근거가 필요하다")
            if (
                self.expected_status == "INSUFFICIENT_EVIDENCE"
                and self.expected_evidence_ids
            ):
                raise ValueError("근거 부족 사례의 정답 인용 목록은 비어 있어야 한다")
        return self


def draft_schema(evidence_ids: list[str]) -> dict:
    """사례마다 만드는 출력 스키마. 모델은 이 모양으로만 생성한다(구조화 출력).

    - 원인 후보의 evidence_ids 값은 주어진 근거 ID 중에서만 고른다(enum).
    - 근거가 없으면 원인 후보를 낼 수 없다(빈 목록만 허용).
    - minItems·maxItems는 API가 강제하지 않아(claude.strict_schema가 뺌) check_draft가 대신 본다.
    """
    schema = AnalysisDraft.model_json_schema()
    cause = schema["$defs"]["InspectionCauseDraft"]
    for part in (schema, cause):
        part["required"] = list(part["properties"])
    ids = cause["properties"]["evidence_ids"]
    ids.pop("default", None)
    if evidence_ids:
        ids["items"] = {"type": "string", "enum": list(evidence_ids)}
        ids["minItems"] = 1
    else:
        schema["properties"]["suspected_causes"]["maxItems"] = 0
    return schema


def load_cases(path: Path) -> list[CheckCase]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    cases = [CheckCase(**case) for case in raw.get("cases", [])]
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("중복 평가 사례 ID")
    return cases


def user_prompt(case: CheckCase) -> str:
    evidence = (
        "\n".join(f"- [{e.evidence_id}] ({e.citation}) {e.text}" for e in case.evidence)
        or "(검색된 근거 없음)"
    )
    return f"사건:\n{case.incident}\n\n근거(evidence):\n{evidence}"


@dataclass
class CaseResult:
    case_id: str
    valid: bool  # JSON·스키마·계약 모두 통과
    status: str | None  # 모델이 낸 status
    expected_status: str
    seconds: float
    usage: LlmUsage | None = None
    error: str | None = None
    result: AnalysisResult | None = None
    citation_match: bool | None = None
    actual_model: str | None = None

    @property
    def status_match(self) -> bool:
        return self.status == self.expected_status

    @property
    def passed(self) -> bool:
        return self.valid and self.status_match and self.citation_match is not False


def check_case(client, case: CheckCase, *, timeout_s: float) -> CaseResult:
    started = time.perf_counter()
    status = None
    # 실패한 요청에 직전 요청의 사용량을 잘못 붙이지 않는다.
    client.last_usage = None
    try:
        text = client.generate_json(
            SYSTEM,
            user_prompt(case),
            timeout_s=timeout_s,
            schema=draft_schema([e.evidence_id for e in case.evidence]),
        )
        draft = AnalysisDraft.model_validate(json.loads(text))
        status = draft.status
        # 스키마로 표현할 수 없는 규칙(근거 부족이면 원인 후보 없음 등)은 생성 뒤 확인한다
        check_draft(draft, {e.evidence_id for e in case.evidence})
        result = AnalysisResult(
            incident_id=case.id,
            evidence=case.evidence,
            model=f"{client.provider}/{client.model_name}",
            prompt_version=PROMPT_VERSION,
            generated_at=datetime.now(UTC),
            **draft.model_dump(),
        )
    except (LlmUnavailableError, LlmModelMissingError, LlmRequestError):
        raise  # 서버·모델이 없으면 다른 사례도 못 한다: 점검을 시작할 수 없는 상황
    except (LlmError, json.JSONDecodeError, ValueError) as exc:
        # 시간 초과·빈 응답·형식·계약 위반은 그 사례의 실패로 남기고 계속한다
        # (pydantic ValidationError도 ValueError다)
        return CaseResult(
            case.id,
            False,
            status,
            case.expected_status,
            time.perf_counter() - started,
            getattr(client, "last_usage", None),
            error=f"{type(exc).__name__}: {_first_line(exc)}",
        )
    cited = {i for c in draft.suspected_causes for i in c.evidence_ids}
    expected = case.expected_evidence_ids
    citation_match = (
        None
        if expected is None
        else (
            bool(cited) and cited <= set(expected)
            if case.expected_status == "OK"
            else not cited
        )
    )
    return CaseResult(
        case.id,
        True,
        status,
        case.expected_status,
        time.perf_counter() - started,
        getattr(client, "last_usage", None),
        result=result,
        citation_match=citation_match,
        actual_model=getattr(client, "last_response_model", None),
    )


@dataclass
class CheckReport:
    model: str
    results: list[CaseResult] = field(default_factory=list)
    effort: str | None = None
    planned_runs: int | None = None

    @property
    def ok(self) -> bool:
        return (
            bool(self.results)
            and all(r.passed for r in self.results)
            and (self.planned_runs is None or len(self.results) == self.planned_runs)
        )


def run_check(
    client,
    cases: list[CheckCase],
    *,
    timeout_s: float,
    repeat: int = 1,
    effort: str | None = None,
    on_result: Callable[[CheckReport], None] | None = None,
) -> CheckReport:
    if not cases or repeat < 1:
        raise ValueError("사례와 1회 이상의 반복이 필요하다")
    report = CheckReport(
        client.model_name, effort=effort, planned_runs=len(cases) * repeat
    )
    for _ in range(repeat):
        for case in cases:
            report.results.append(check_case(client, case, timeout_s=timeout_s))
            if on_result:
                on_result(report)
    return report


def report_data(report: CheckReport) -> dict:
    """비교·재현용 결과만 내보낸다. 요청·응답 본문은 포함하지 않는다."""
    times = sorted(r.seconds for r in report.results)
    usages = [r.usage for r in report.results if r.usage is not None]
    return {
        "model": report.model,
        "actual_models": {
            m: sum(r.actual_model == m for r in report.results)
            for m in sorted({r.actual_model for r in report.results if r.actual_model})
        },
        "actual_model_unreported_runs": sum(
            r.actual_model is None for r in report.results
        ),
        "effort": report.effort,
        "prompt_version": PROMPT_VERSION,
        "planned_runs": report.planned_runs,
        "completed_runs": len(report.results),
        "passed": report.ok,
        "valid": sum(r.valid for r in report.results),
        "status_match": sum(r.status_match for r in report.results),
        "citation_match": sum(r.citation_match is True for r in report.results),
        "citation_evaluated": sum(r.citation_match is not None for r in report.results),
        "mean_seconds": fmean(times) if times else None,
        "median_seconds": median(times) if times else None,
        "p95_seconds": times[max(0, ceil(len(times) * 0.95) - 1)] if times else None,
        "input_tokens": sum(u.input_tokens for u in usages),
        "output_tokens": sum(u.output_tokens for u in usages),
        "cache_read_input_tokens": sum(u.cache_read_input_tokens for u in usages),
        "cache_creation_input_tokens": sum(
            u.cache_creation_input_tokens for u in usages
        ),
        "usage_reported_runs": len(usages),
        "results": [
            {
                "case_id": r.case_id,
                "actual_model": r.actual_model,
                "valid": r.valid,
                "status": r.status,
                "expected_status": r.expected_status,
                "status_match": r.status_match,
                "citation_match": r.citation_match,
                "passed": r.passed,
                "seconds": r.seconds,
                "error_type": r.error.split(":", 1)[0] if r.error else None,
            }
            for r in report.results
        ],
    }


def format_markdown(report: CheckReport, *, include_example: bool = True) -> str:
    results = report.results
    valid = sum(r.valid for r in results)
    match = sum(r.status_match for r in results)
    usages = [r.usage for r in results if r.usage]
    tokens_in = sum(u.input_tokens for u in usages)
    tokens_out = sum(u.output_tokens for u in usages)
    lines = [
        f"# LLM 구조화 출력 점검 — {report.model}",
        "",
        f"- 프롬프트: `{PROMPT_VERSION}`, 실행 {len(results)}회",
        f"- 스키마·계약 통과: **{valid}/{len(results)}**",
        f"- 기대 상태 일치: **{match}/{len(results)}**",
        f"- effort: `{report.effort or '기록 없음'}`, 종합 통과: **{sum(r.passed for r in results)}/{len(results)}**",
        f"- 정답 근거 인용: {sum(r.citation_match is True for r in results)}/{sum(r.citation_match is not None for r in results)} (ID 대조, 내용의 의미 검증은 별도)",
        f"- 토큰 합계: 입력 {tokens_in} / 출력 {tokens_out}",
        "",
        "| 사례 | 종합 통과 | 상태(기대) | 원인 후보 | 초 | 출력 토큰 | 오류 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        causes = len(r.result.suspected_causes) if r.result else "-"
        tokens = r.usage.output_tokens if r.usage else "-"
        lines.append(
            f"| {r.case_id} | {'✅' if r.passed else '❌'} | {r.status or '-'}"
            f"({r.expected_status}) | {causes} | {r.seconds:.1f} | {tokens} | "
            f"{r.error or ''} |"
        )
    sample = next((r.result for r in results if r.result), None)
    if sample is not None and include_example:
        lines += [
            "",
            "## 출력 예시",
            "",
            "```json",
            sample.model_dump_json(
                indent=2, exclude={"evidence", "generated_at", "model"}
            ),
            "```",
        ]
    return "\n".join(lines) + "\n"


def _first_line(exc: Exception) -> str:
    return str(exc).splitlines()[0][:200]
