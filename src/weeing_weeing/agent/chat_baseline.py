"""챗봇 지연 기준선 측정 (#215).

같은 질문 세트를 차례로 실행해 질문별 전체 시간, LLM 호출 수·목적별 시간, 토큰·캐시 토큰,
근거 검토 횟수를 모은다. 서비스의 last_run(ChatRunUsage)만 쓰므로 Langfuse가 없어도 잰다.
질문 본문·응답 본문·키는 결과에 남기지 않는다(질문 ID·유형·상태·숫자만).

LLM·검색 구현은 호출하는 쪽이 service_factory로 넘긴다. 스크립트는 기본으로 계획만 보여 주고,
--replay(재생 LLM, 비용 0)나 --execute(실제 Claude, 유료)일 때만 실행한다.
"""

import statistics
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from weeing_weeing.contracts import ChatContext, ChatQuestion


@dataclass(frozen=True)
class LatencyCase:
    case_id: str
    kind: str
    question: str
    expected_status: str | None = None


@dataclass
class LatencyRow:
    case_id: str
    kind: str
    status: str
    expected_status: str | None
    failure_code: str | None
    elapsed_s: float
    llm_calls: int
    dialogue_calls: int
    grounding_calls: int
    dialogue_s: float
    grounding_s: float
    other_s: float  # 전체 - LLM 호출 합계: 검색·DB·검증 등
    slowest_call_s: float
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    tools: list[str] = field(default_factory=list)


def load_latency_cases(path: str | Path) -> list[LatencyCase]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("지원하지 않는 schema_version")
    cases = [
        LatencyCase(
            case_id=item["id"],
            kind=item["kind"],
            question=item["question"],
            expected_status=item.get("expected_status"),
        )
        for item in data.get("cases", [])
    ]
    ids = [case.case_id for case in cases]
    if not cases or len(ids) != len(set(ids)):
        raise ValueError("질문이 없거나 id가 중복됨")
    return cases


def _sum_tokens(calls, attr: str) -> int | None:
    values = [getattr(call.usage, attr, None) for call in calls]
    if not values or any(value is None for value in values):
        return None  # 사용량을 모르는 호출이 있으면 0으로 채우지 않는다
    return sum(values)


def measure_case(service: Any, case: LatencyCase, *, timeout_s: float) -> LatencyRow:
    """질문 1건을 실행한다. 실패도 FAILED 행으로 기록하고 다음 질문으로 넘어간다."""
    started = time.monotonic()
    response = service.reply(
        ChatQuestion(request_id=uuid4(), question=case.question),
        context=ChatContext(),
        timeout_s=timeout_s,
    )
    elapsed = time.monotonic() - started
    run = getattr(service, "last_run", None)
    calls = tuple(run.calls) if run else ()
    dialogue = [c for c in calls if c.purpose == "dialogue"]
    grounding = [c for c in calls if c.purpose == "grounding"]
    llm_s = sum(c.elapsed_s for c in calls)
    return LatencyRow(
        case_id=case.case_id,
        kind=case.kind,
        status=response.status,
        expected_status=case.expected_status,
        failure_code=response.failure.code if response.failure else None,
        elapsed_s=round(elapsed, 3),
        llm_calls=len(calls),
        dialogue_calls=len(dialogue),
        grounding_calls=len(grounding),
        dialogue_s=round(sum(c.elapsed_s for c in dialogue), 3),
        grounding_s=round(sum(c.elapsed_s for c in grounding), 3),
        other_s=round(max(elapsed - llm_s, 0.0), 3),
        slowest_call_s=round(max((c.elapsed_s for c in calls), default=0.0), 3),
        input_tokens=_sum_tokens(calls, "input_tokens"),
        output_tokens=_sum_tokens(calls, "output_tokens"),
        cache_read_tokens=_sum_tokens(calls, "cache_read_input_tokens"),
        tools=list(run.tool_names) if run else [],
    )


def run_latency_baseline(
    service_factory: Callable[[], Any],
    cases: Sequence[LatencyCase],
    *,
    timeout_s: float = 120,
    on_row: Callable[[LatencyRow], None] | None = None,
) -> list[LatencyRow]:
    """질문마다 새 서비스를 만든다(API와 같은 요청별 서비스, 앞 질문 문맥 없음)."""
    rows = []
    for case in cases:
        row = measure_case(service_factory(), case, timeout_s=timeout_s)
        rows.append(row)
        if on_row:
            on_row(row)
    return rows


def _percentile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1]


def summarize(rows: Sequence[LatencyRow]) -> dict[str, Any]:
    elapsed = [row.elapsed_s for row in rows]
    total = sum(elapsed) or 1.0
    return {
        "questions": len(rows),
        "p50_s": round(statistics.median(elapsed), 2),
        "p95_s": round(_percentile(elapsed, 95), 2),
        "mean_s": round(statistics.fmean(elapsed), 2),
        "max_s": round(max(elapsed), 2),
        "mean_llm_calls": round(statistics.fmean(r.llm_calls for r in rows), 2),
        "re_reviewed": sum(r.grounding_calls > 1 for r in rows),
        "share_dialogue": round(sum(r.dialogue_s for r in rows) / total, 3),
        "share_grounding": round(sum(r.grounding_s for r in rows) / total, 3),
        "share_other": round(sum(r.other_s for r in rows) / total, 3),
        "status_matches": sum(
            r.expected_status is not None and r.status == r.expected_status
            for r in rows
        ),
        "with_expected": sum(r.expected_status is not None for r in rows),
    }


def format_latency_report(
    rows: Sequence[LatencyRow], *, title: str, settings: dict[str, Any]
) -> str:
    s = summarize(rows)
    lines = [
        f"# {title}",
        "",
        "| 설정 | 값 |",
        "|---|---|",
        *[f"| {key} | {value} |" for key, value in settings.items()],
        "",
        "## 요약",
        "",
        f"- 질문 {s['questions']}개, p50 **{s['p50_s']}초**, p95 {s['p95_s']}초, 평균 {s['mean_s']}초, 최대 {s['max_s']}초",
        f"- 질문당 LLM 호출 평균 {s['mean_llm_calls']}번, 근거 재검토 발생 {s['re_reviewed']}건",
        f"- 시간 비중: 도구 루프 LLM {s['share_dialogue']:.0%} / 근거 검토 LLM {s['share_grounding']:.0%} / 그 외(검색·DB·검증) {s['share_other']:.0%}",
        f"- 기대 상태 일치 {s['status_matches']}/{s['with_expected']} (참고값)",
        "",
        "## 질문별",
        "",
        "| ID | 유형 | 상태 | 전체(초) | LLM 호출(루프+검토) | 루프(초) | 검토(초) | 그 외(초) | 가장 긴 호출(초) | 입력/출력 토큰 | 캐시 읽기 | 도구 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        status = r.status + (f"({r.failure_code})" if r.failure_code else "")
        if r.expected_status and r.status != r.expected_status:
            status += f" ≠{r.expected_status}"
        tokens = (
            f"{r.input_tokens}/{r.output_tokens}"
            if r.input_tokens is not None
            else "미확인"
        )
        lines.append(
            f"| {r.case_id} | {r.kind} | {status} | {r.elapsed_s} | {r.llm_calls} "
            f"({r.dialogue_calls}+{r.grounding_calls}) | {r.dialogue_s} | {r.grounding_s} "
            f"| {r.other_s} | {r.slowest_call_s} | {tokens} | "
            f"{r.cache_read_tokens if r.cache_read_tokens is not None else '미확인'} "
            f"| {', '.join(r.tools) or '-'} |"
        )
    return "\n".join(lines) + "\n"


def rows_as_dicts(rows: Sequence[LatencyRow]) -> list[dict[str, Any]]:
    return [asdict(row) for row in rows]
