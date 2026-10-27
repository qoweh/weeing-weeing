"""LLM 구조화 출력 점검 (#10, make llm-check).

사례(data/eval/llm_cases_v1.toml)마다 사건 설명과 근거를 주고, 모델이 JSON 스키마대로
분석 초안을 내는지 확인한다. 모델 선정·비교(양자화·크기)에 같은 사례를 쓴다.

    반드시 통과: JSON 파싱 → AnalysisDraft 스키마 → AnalysisResult 계약(인용은 실제 근거만)
    숫자로 기록: 기대 상태(OK / INSUFFICIENT_EVIDENCE) 일치율, 응답 시간, 초당 토큰

프롬프트는 점검용 최소본이다. 실제 분석 프롬프트와 워크플로는 #11~#13에서 만든다.
"""

import json
import time
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from weeing_weeing.agent.errors import (
    LlmError,
    LlmModelMissingError,
    LlmUnavailableError,
    LlmUsage,
)
from weeing_weeing.contracts import AnalysisResult, CauseCandidate, Evidence

PROMPT_VERSION = "llm-check-v3"

SYSTEM = """너는 배터리 트레이 이송 설비의 정비 보조 AI다. 한국어로 답한다.
할 일: 사건과 근거(evidence)를 읽고, 근거에 적힌 내용으로 원인 후보와 점검 순서를 제안한다.

규칙:
1. 근거에 있는 내용만 쓴다. 근거에 없는 원인·수치·절차를 지어내지 않는다.
2. 근거가 사건의 코드나 현상(예: 같은 룰 코드, 같은 센서·증상)을 다루면,
   그 근거에 적힌 점검 대상을 원인 후보로 제시하고 status는 OK로 한다.
   원인 후보는 "가능성"을 제시하는 것이지 원인을 확정하는 것이 아니다.
   likelihood(상·중·하)로 가능성을 나타낸다.
3. 원인 후보마다 그 내용을 담은 근거의 evidence_id를 evidence_ids에 넣는다.
   목록에 없는 ID는 쓰지 않는다.
   basis에는 그 후보를 뒷받침하는 사건의 센서 관측을 요약한다(근거 ID를 적지 않는다).
4. 근거가 없거나, 있어도 사건의 코드·현상과 관련이 없으면 status는 INSUFFICIENT_EVIDENCE다.
   이때 suspected_causes는 비우고 additional_checks에 더 확인할 것을 쓴다.
5. 정지 해제·재가동·부품 교체처럼 사람의 승인이 필요한 조치는 actions_requiring_approval에 넣는다.
6. 지정한 JSON 형식으로만 답한다. status는 다른 칸을 모두 쓴 뒤 마지막에 정한다."""


class AnalysisDraft(BaseModel):
    """LLM이 채우는 칸. incident_id·근거 목록·모델명·시각은 시스템이 붙인다.

    칸 순서가 곧 생성 순서다. status를 맨 뒤에 두어 근거를 정리한 다음 판단하게 한다.
    """

    observed_facts: str
    suspected_causes: list[CauseCandidate] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    actions_requiring_approval: list[str] = Field(default_factory=list)
    additional_checks: list[str] = Field(default_factory=list)
    limitations: str | None = None
    status: Literal["OK", "INSUFFICIENT_EVIDENCE"]


class CheckCase(BaseModel):
    id: str
    incident: str
    expected_status: Literal["OK", "INSUFFICIENT_EVIDENCE"]
    evidence: list[Evidence] = Field(default_factory=list)


def draft_schema(evidence_ids: list[str]) -> dict:
    """사례마다 만드는 출력 스키마. Ollama가 이 모양으로만 생성한다(문법 제약).

    - 원인 후보의 evidence_ids는 필수이고 최소 1개, 값은 주어진 근거 ID 중에서만 고른다.
      (기본값이 있는 칸은 모델이 건너뛸 수 있어서, 근거 ID를 basis에 적고 빠뜨린 적이 있다)
    - 근거가 없으면 원인 후보를 낼 수 없다(빈 목록만 허용).
    - 모든 칸을 required로 둔다. Ollama(llama.cpp)는 required 칸을 먼저, 나머지를 뒤에
      생성하고 required가 아닌 칸은 건너뛸 수 있다. 전부 required여야 정의한 순서대로
      쓰고 status를 마지막에 정한다.
    """
    schema = AnalysisDraft.model_json_schema()
    cause = schema["$defs"]["CauseCandidate"]
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
    return [CheckCase(**case) for case in raw.get("cases", [])]


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

    @property
    def status_match(self) -> bool:
        return self.status == self.expected_status


def check_case(client, case: CheckCase, *, timeout_s: float) -> CaseResult:
    started = time.perf_counter()
    status = None
    try:
        text = client.generate_json(
            SYSTEM,
            user_prompt(case),
            timeout_s=timeout_s,
            schema=draft_schema([e.evidence_id for e in case.evidence]),
        )
        draft = AnalysisDraft.model_validate(json.loads(text))
        status = draft.status
        result = AnalysisResult(
            incident_id=case.id,
            evidence=case.evidence,
            model=f"ollama/{client.model_name}",
            prompt_version=PROMPT_VERSION,
            generated_at=datetime.now(UTC),
            **draft.model_dump(),
        )
        if draft.status != "OK" and draft.suspected_causes:
            # 스키마로는 "근거 부족이면 원인 후보 없음"을 표현할 수 없어 생성 뒤 확인한다
            raise ValueError("INSUFFICIENT_EVIDENCE인데 원인 후보가 있음")
    except (LlmUnavailableError, LlmModelMissingError):
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
    return CaseResult(
        case.id,
        True,
        status,
        case.expected_status,
        time.perf_counter() - started,
        getattr(client, "last_usage", None),
        result=result,
    )


@dataclass
class CheckReport:
    model: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.valid for r in self.results)


def run_check(
    client, cases: list[CheckCase], *, timeout_s: float, repeat: int = 1
) -> CheckReport:
    report = CheckReport(client.model_name)
    for _ in range(repeat):
        for case in cases:
            report.results.append(check_case(client, case, timeout_s=timeout_s))
    return report


def format_markdown(report: CheckReport) -> str:
    results = report.results
    valid = sum(r.valid for r in results)
    match = sum(r.status_match for r in results)
    usages = [r.usage for r in results if r.usage and r.usage.eval_s]
    speed = sum(u.tokens_per_s for u in usages) / len(usages) if usages else 0.0
    lines = [
        f"# LLM 구조화 출력 점검 — {report.model}",
        "",
        f"- 프롬프트: `{PROMPT_VERSION}`, 실행 {len(results)}회",
        f"- 스키마·계약 통과: **{valid}/{len(results)}**",
        f"- 기대 상태 일치: **{match}/{len(results)}**",
        f"- 생성 속도(출력 생성 구간 평균): {speed:.1f} 토큰/초",
        "",
        "| 사례 | 통과 | 상태(기대) | 원인 후보 | 초 | 출력 토큰 | 오류 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        causes = len(r.result.suspected_causes) if r.result else "-"
        tokens = r.usage.output_tokens if r.usage else "-"
        lines.append(
            f"| {r.case_id} | {'✅' if r.valid else '❌'} | {r.status or '-'}"
            f"({r.expected_status}) | {causes} | {r.seconds:.1f} | {tokens} | "
            f"{r.error or ''} |"
        )
    sample = next((r.result for r in results if r.result), None)
    if sample is not None:
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
