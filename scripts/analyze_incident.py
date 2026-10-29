"""사건 하나를 사건 분석 에이전트로 분석한다 (#102, make analyze).

Claude가 근거 검색 도구를 골라 부르고 원인 후보를 제출한다. 결과는 AnalysisResult JSON과
도구 호출 기록이다. DB에는 저장하지 않는다(탐지 결과 저장 연결은 #61).

입력: --incident Incident JSON 파일(기본 data/eval/incident_p03_demo.json),
      .env(ANTHROPIC_API_KEY·LLM_MODEL·LLM_EFFORT·AGENT_MAX_TURNS), 색인된 벡터 DB(make index)
출력: 터미널에 결과 JSON·도구 호출·토큰 수
종료 코드: 0 OK 또는 INSUFFICIENT_EVIDENCE / 1 FAILED / 2 입력·설정 문제로 시작 못 함

    make analyze
    make analyze ARGS="--incident 사건.json"
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from weeing_weeing.agent.interface import get_analyzer
from weeing_weeing.config import PROJECT_ROOT
from weeing_weeing.contracts import Incident
from weeing_weeing.rag.interface import get_retriever

DEMO = PROJECT_ROOT / "data/eval/incident_p03_demo.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--incident", type=Path, default=DEMO)
    args = parser.parse_args(argv)

    try:
        incident = Incident.model_validate_json(args.incident.read_text("utf-8"))
        analyzer = get_analyzer(get_retriever())
    except (OSError, ValidationError, ValueError) as exc:
        print(f"시작하지 못함: {exc}", file=sys.stderr)
        return 2

    result = analyzer.analyze(incident)
    print(result.model_dump_json(indent=2))
    memory = getattr(analyzer, "last_memory", None)
    if memory is not None:
        print(f"\n도구 호출 {len(memory.tool_calls)}회, LLM 호출 {memory.turns}회")
        for call in memory.tool_calls:
            mark = "✅" if call.ok else "❌"
            print(
                f"  {mark} {call.name} {json.dumps(call.input, ensure_ascii=False)[:120]}"
            )
        u = memory.usage
        print(
            f"토큰: 입력 {u.input_tokens} / 출력 {u.output_tokens}, {u.total_s:.1f}초"
        )
    return 1 if result.status == "FAILED" else 0


if __name__ == "__main__":
    sys.exit(main())
