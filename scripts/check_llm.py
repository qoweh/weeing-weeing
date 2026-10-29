"""LLM(Claude)이 구조화 출력(JSON 스키마)과 근거 인용 규칙을 지키는지 점검한다 (#101).

입력: data/eval/llm_cases_v1.toml, .env(ANTHROPIC_API_KEY·LLM_MODEL·LLM_EFFORT·LLM_TIMEOUT_S)
출력: 터미널 요약, outputs/llm_check/report-<시각>.md
종료 코드: 0 모든 사례가 스키마·계약 통과 / 1 통과 못 한 사례 있음 / 2 키·모델·설정 문제로 시작 못 함
비용: 사례마다 API를 한 번 부른다(사례 4개 × 반복 횟수).

    make llm-check                                            # .env의 모델
    make llm-check ARGS="--model claude-sonnet-5-5 --repeat 3"
    make llm-check ARGS="--effort low"                        # 생각 깊이 비교
"""

import argparse
import dataclasses
import sys
from datetime import datetime
from pathlib import Path

from weeing_weeing.agent.interface import LlmError, get_llm_client
from weeing_weeing.agent.llm_check import format_markdown, load_cases, run_check
from weeing_weeing.config import PROJECT_ROOT, get_settings

CASES = PROJECT_ROOT / "data/eval/llm_cases_v1.toml"


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("1 이상이어야 한다")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", help="모델(기본: .env의 LLM_MODEL)")
    parser.add_argument(
        "--repeat", type=_positive, default=1, help="사례마다 반복 횟수(1 이상)"
    )
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="생각 깊이(기본: .env의 LLM_EFFORT)",
    )
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--out", type=Path, help="보고서 경로")
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
        overrides = {}
        if args.model:
            overrides["llm_model"] = args.model
        if args.effort:
            overrides["llm_effort"] = args.effort
        settings = dataclasses.replace(settings, **overrides)
        client = get_llm_client(settings)
        cases = load_cases(args.cases)
        if not cases:
            raise ValueError(f"{args.cases}에 사례가 없다")
        print(f"모델 {client.model_name} / 사례 {len(cases)}개 × {args.repeat}회")
        report = run_check(
            client, cases, timeout_s=settings.llm_timeout_s, repeat=args.repeat
        )
    except (LlmError, ValueError, OSError) as exc:
        print(f"시작하지 못함: {exc}", file=sys.stderr)
        return 2

    text = format_markdown(report)
    out = args.out or PROJECT_ROOT / (
        f"outputs/llm_check/report-{datetime.now():%Y%m%d-%H%M%S}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text.split("\n## 출력 예시")[0])
    print(f"보고서: {out}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
