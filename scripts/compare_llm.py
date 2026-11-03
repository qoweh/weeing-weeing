"""#106 모델·effort 비교. 기본은 호출 계획만 표시한다. --execute는 유료 API 실행."""

import argparse
import dataclasses
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from weeing_weeing.agent.interface import (
    CheckReport,
    LlmError,
    LlmRequestError,
    check_case,
    get_llm_client,
    llm_check_data,
    load_llm_cases,
)
from weeing_weeing.config import PROJECT_ROOT, get_settings

# 팀 비용 합의: 기본 실행 계획에는 Opus를 포함하지 않는다(D-30).
DEFAULT_SETTINGS = ["claude-sonnet-5-5:medium"]


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수가 필요하다")
    return value


def variant(value):
    model, separator, effort = value.rpartition(":")
    if (
        not separator
        or not model.strip()
        or effort not in {"low", "medium", "high", "xhigh", "max"}
    ):
        raise argparse.ArgumentTypeError("MODEL:EFFORT 형식이 필요하다")
    return model, effort


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def markdown(plan, reports):
    lines = [
        "# Claude 모델 비교 (#106)",
        "",
        f"- 실행 시각(UTC): {plan['created_at']}",
        f"- 사례 SHA256: `{plan['cases_sha256']}`",
        f"- Agent 코드 SHA256: `{plan['agent_sha256']}`",
        "- 고정 근거 LLM 평가다. 실제 RAG 검색·센서 조회·Unreal 전송 시간은 포함하지 않는다.",
        "- 인용 검사는 정답 ID와의 대조이며 내용의 의미 정확성·안전성을 보증하지 않는다.",
        "- 시간은 API 왕복·대기를 포함한다. P95는 nearest-rank 방식이며 소표본에서는 참고값이다.",
        "- 실제 청구 비용은 토큰만으로 확정하지 않는다. 캐시·계약 단가는 별도 확인한다.",
        "",
        "| 모델 | effort | 완료/계획 | 형식 | 상태 | 정답 인용 | 평균초 | 중앙초 | P95초 | 입력/출력 토큰 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        d = llm_check_data(report)
        times = [
            f"{d[k]:.2f}" if d[k] is not None else "-"
            for k in ("mean_seconds", "median_seconds", "p95_seconds")
        ]
        lines.append(
            f"| {report.model} | {report.effort} | {len(report.results)}/{report.planned_runs} | {d['valid']} | {d['status_match']} | {d['citation_match']}/{d['citation_evaluated']} | {' | '.join(times)} | {d['input_tokens']}/{d['output_tokens']} |"
        )
    lines += [
        "",
        "## 기본값 결정",
        "",
        "미결정. 통과율·인용 내용·부적절한 확정/조치 여부를 사람이 검토한 뒤 DECISIONS에 기록한다.",
        "속도만으로 기본 설정이나 RAG 관련도 기준값을 자동 변경하지 않는다.",
        "",
        "- [ ] 원인 후보와 실제 인용 문장이 맞는지 검토",
        "- [ ] 근거 부족·방해 근거에서 추측을 멈추는지 검토",
        "- [ ] 센서 신호와 실제 물체 존재를 구분하는지 검토",
        "- [ ] 승인 필요한 조치를 구분하는지 검토",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", type=Path, default=PROJECT_ROOT / "data/eval/llm_cases_v1.toml"
    )
    parser.add_argument(
        "--setting",
        action="append",
        type=variant,
        help="MODEL:EFFORT; 여러 번 지정 가능",
    )
    parser.add_argument(
        "--case-id", action="append", help="지정한 사례만 선택; 여러 번 지정 가능"
    )
    parser.add_argument("--repeat", type=positive, default=3)
    parser.add_argument(
        "--max-calls",
        type=positive,
        default=40,
        help="애플리케이션 요청 수 상한. SDK 재시도는 포함하지 않음",
    )
    parser.add_argument(
        "--execute", action="store_true", help="계획에 따라 실제 유료 API를 호출한다"
    )
    parser.add_argument(
        "--out", type=Path, help="새 결과 폴더. 기존 폴더를 덮어쓰지 않음"
    )
    parser.add_argument(
        "--review-output",
        action="store_true",
        help="사람 검토용 모델 응답을 로컬 폴더에 저장. 공유 문서에는 복사하지 않음",
    )
    args = parser.parse_args(argv)
    try:
        cases = load_llm_cases(args.cases)
        if args.case_id:
            if set(args.case_id) - {c.id for c in cases}:
                raise ValueError("없는 사례 ID")
            cases = [c for c in cases if c.id in args.case_id]
        if not cases:
            raise ValueError("평가 사례가 없다")
        variants = args.setting or [variant(v) for v in DEFAULT_SETTINGS]
        if len(set(variants)) != len(variants):
            raise ValueError("중복 모델·effort 설정")
        calls = len(cases) * args.repeat * len(variants)
        agent_files = sorted((PROJECT_ROOT / "src/weeing_weeing/agent").glob("*.py"))
        plan = {
            "created_at": datetime.now(UTC).isoformat(),
            "cases_file": args.cases.name,
            "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
            "agent_sha256": hashlib.sha256(
                b"".join(p.name.encode() + p.read_bytes() for p in agent_files)
            ).hexdigest(),
            "case_ids": [c.id for c in cases],
            "repeat": args.repeat,
            "settings": [{"model": m, "effort": e} for m, e in variants],
            "planned_calls": calls,
            "max_calls": args.max_calls,
            "executed": args.execute,
            "note": "SDK 내부 재시도로 실제 HTTP 요청 수는 더 많을 수 있음",
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
        if not args.execute:
            print(
                "계획 확인 완료. 실제 호출 0회. --execute를 지정해야 유료 평가를 시작합니다."
            )
            return 0
        if calls > args.max_calls:
            raise ValueError("계획 호출 수가 --max-calls 상한을 초과한다")
        settings = get_settings()
        plan["timeout_s"] = settings.llm_timeout_s
        output = args.out or PROJECT_ROOT / "outputs/llm_evaluation" / datetime.now(
            UTC
        ).strftime("%Y%m%d-%H%M%S-%f")
        output.mkdir(parents=True, exist_ok=False)
        save(output / "plan.json", plan)
        reports = []
        completed = 0

        def checkpoint():
            save(
                output / "results.json",
                {"plan": plan, "reports": [llm_check_data(r) for r in reports]},
            )
            (output / "report.md").write_text(markdown(plan, reports), encoding="utf-8")

        checkpoint()
        try:
            for model, effort in variants:
                report = CheckReport(
                    model, effort=effort, planned_runs=len(cases) * args.repeat
                )
                reports.append(report)
                checkpoint()
                client = get_llm_client(
                    dataclasses.replace(settings, llm_model=model, llm_effort=effort),
                    entrypoint="llm-evaluation",
                )
                try:
                    for repetition in range(args.repeat):
                        for case in cases:
                            print(
                                f"[시작 {completed + 1}/{calls}] {model}/{effort} {case.id} 반복={repetition + 1}",
                                flush=True,
                            )
                            plan["attempted_calls"] = completed + 1
                            result = check_case(
                                client, case, timeout_s=settings.llm_timeout_s
                            )
                            report.results.append(result)
                            completed += 1
                            checkpoint()
                            if args.review_output and result.result is not None:
                                (output / f"response-{completed:04d}.json").write_text(
                                    result.result.model_dump_json(indent=2),
                                    encoding="utf-8",
                                )
                            print(
                                f"[완료 {completed}/{calls}] {'PASS' if result.passed else 'FAIL'} 상태={result.status} {result.seconds:.1f}초",
                                flush=True,
                            )
                finally:
                    client.tracer.flush()
        except (LlmError, KeyboardInterrupt) as exc:
            plan["termination"] = {"error_type": type(exc).__name__}
            if isinstance(exc, LlmRequestError):
                plan["termination"].update(
                    http_status=exc.status_code, parameter_hint=exc.parameter_hint
                )
            checkpoint()
            print(
                f"평가 중단: {type(exc).__name__} {plan['termination']}. 완료 결과 보존: {output}",
                flush=True,
            )
            return 2
        print(f"평가 완료: {output / 'report.md'}", flush=True)
        return 0 if all(r.ok for r in reports) else 1
    except (OSError, ValueError) as exc:
        print(f"시작/기록하지 못함: {type(exc).__name__}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
