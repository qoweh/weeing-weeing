"""챗봇 지연 기준선 측정 (#215). 같은 질문 세트로 지연 개선 전후를 비교한다.

- 기본: 실행 계획(질문 수·예상 호출)만 보여 주고 아무것도 호출하지 않는다.
- --replay: 재생 LLM(비용 0)으로 측정 흐름을 확인한다. 기본 지식은 샘플 문서, --real-knowledge면
  프로젝트 DB·벡터 색인(EMBEDDING_PROVIDER=hashing·리랭커 꺼짐일 때만).
- --execute: 실제 Claude와 프로젝트 DB·색인으로 잰다(유료). 실행 전에 확인을 묻는다(--yes로 생략).

결과: outputs/chat_baseline/report-<시각>.md 와 같은 이름의 .json. 질문·응답 본문은 남기지 않는다.
"""

import argparse
import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path

from weeing_weeing.agent.interface import (
    format_latency_report,
    get_chat_service,
    get_replay_llm_client,
    latency_rows_as_dicts,
    load_latency_cases,
    replay_sample_knowledge,
    run_latency_baseline,
)
from weeing_weeing.config import PROJECT_ROOT, get_settings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", type=Path, default=PROJECT_ROOT / "data/eval/chat_latency_v1.toml"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="재생 LLM으로 실행(비용 0)")
    mode.add_argument("--execute", action="store_true", help="실제 Claude로 실행(유료)")
    parser.add_argument("--real-knowledge", action="store_true")
    parser.add_argument("--only", help="쉼표로 구분한 질문 ID만 실행(예: L01,L05)")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument(
        "--label", default="", help="보고서 제목에 붙일 이름(예: before-218)"
    )
    parser.add_argument(
        "--out", type=Path, default=PROJECT_ROOT / "outputs/chat_baseline"
    )
    parser.add_argument("--yes", action="store_true", help="유료 실행 확인 생략")
    args = parser.parse_args(argv)

    cases = load_latency_cases(args.cases)
    if args.only:
        wanted = {item.strip() for item in args.only.split(",")}
        cases = [case for case in cases if case.case_id in wanted]
        if not cases:
            print("--only에 맞는 질문이 없다", file=sys.stderr)
            return 2
    settings = get_settings()
    if not (args.replay or args.execute):
        print(f"질문 {len(cases)}개: {', '.join(c.case_id for c in cases)}")
        print(f"모델 {settings.llm_model} / effort {settings.llm_effort}")
        print(
            "질문당 LLM 호출 보통 3~5번(도구 루프 2~3 + 근거 검토 1~2). 실행은 --execute(유료)"
        )
        print("측정 흐름만 확인하려면 --replay(비용 0)")
        return 0

    if args.replay:
        settings = dataclasses.replace(settings, langfuse_tracing_environment="test")
    real = args.execute or args.real_knowledge
    if (
        real
        and args.replay
        and (settings.embedding_provider != "hashing" or settings.reranker_model)
    ):
        print(
            "--replay --real-knowledge는 EMBEDDING_PROVIDER=hashing, RERANKER_MODEL 비움일 때만",
            file=sys.stderr,
        )
        return 2
    if args.execute and not args.yes:
        answer = input(
            f"실제 Claude({settings.llm_model})로 {len(cases)}문항을 실행한다(유료). 계속? [y/N] "
        )
        if answer.strip().lower() != "y":
            print("취소했다")
            return 1

    if real:
        from weeing_weeing.api.chat_knowledge import get_chat_knowledge

        knowledge = get_chat_knowledge()
    else:
        knowledge = replay_sample_knowledge()

    clients = []

    def factory():
        client = (
            get_replay_llm_client(settings, entrypoint="chat-baseline")
            if args.replay
            else None
        )
        service = get_chat_service(knowledge, client=client, settings=settings)
        clients.append(service)
        return service

    def progress(row):
        print(
            f"{row.case_id} {row.status} {row.elapsed_s}s calls={row.llm_calls}",
            flush=True,
        )

    rows = run_latency_baseline(factory, cases, timeout_s=args.timeout, on_row=progress)
    mode_name = "replay" if args.replay else "execute"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    title = f"챗봇 지연 기준선 {stamp} {args.label}".strip()
    report = format_latency_report(
        rows,
        title=title,
        settings={
            "모드": mode_name,
            "모델": "replay-no-cost" if args.replay else settings.llm_model,
            "effort": settings.llm_effort,
            "지식": "프로젝트 DB·색인" if real else "샘플 문서",
            "질문 세트": args.cases.name,
        },
    )
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"report-{stamp}{'-' + args.label if args.label else ''}"
    path.with_suffix(".md").write_text(report, encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(latency_rows_as_dicts(rows), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    for service in clients:  # 기록을 보내고 연결을 닫는다
        close = getattr(getattr(service, "_client", None), "close", None)
        if close:
            close()
    print(report)
    print(f"저장: {path.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
