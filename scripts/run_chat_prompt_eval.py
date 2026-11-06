"""프롬프트 A/B 5문항×2=10요청. 기본은 무과금 계획, --execute만 실제 실행."""

import argparse
import dataclasses
import getpass
import hashlib
import importlib
import json
import os
import statistics
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "data/eval/chat_prompt_v11_cases.json"
BASELINE_PATH = ROOT / "data/eval/chat_prompt_v11_baseline.json"
ABORT_CODES = {"LLM_AUTHENTICATION", "RATE_LIMITED", "SEARCH_UNAVAILABLE"}


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def load_plan():
    plan = json.loads(CASE_PATH.read_text())
    cases = plan["cases"]
    if len(cases) != 5 or len({c["id"] for c in cases}) != 5:
        raise ValueError("Exactly five distinct cases required")
    if any(len(c["questions"]) != 1 for c in cases):
        raise ValueError("Pilot requires one question per case")
    return plan


@contextmanager
def prompt_variant(modules, prompts, version):
    """프롬프트만 메모리에서 교체한다. 같은 코드/조회기를 두 변형이 사용한다."""
    saved = []
    try:
        for filename, values in prompts.items():
            module = modules[filename]
            for key, value in values.items():
                saved.append((module, key, getattr(module, key)))
                setattr(module, key, value)
        chat = modules["chat.py"]
        saved.append((chat, "CHAT_PROMPT_VERSION", chat.CHAT_PROMPT_VERSION))
        chat.CHAT_PROMPT_VERSION = version
        yield
    finally:
        for module, key, value in reversed(saved):
            setattr(module, key, value)


def summary(rows):
    variants = {}
    for variant in ("baseline", "candidate"):
        selected = [r for r in rows if r["variant"] == variant]
        variants[variant] = {
            "requests": len(selected),
            "llm_calls": sum(r["llm_calls"] for r in selected),
            "http_attempts": sum(r["http_attempts"] for r in selected),
            "tool_turns": sum(r["tool_turns"] for r in selected),
            "review_calls": sum(r["review_calls"] for r in selected),
            "mean_latency_s": statistics.mean(r["elapsed_s"] for r in selected)
            if selected
            else None,
            "failed_requests": sum(r["status"] == "FAILED" for r in selected),
        }
    pairs = []
    for case in sorted({r["case"] for r in rows}):
        pair = {r["variant"]: r for r in rows if r["case"] == case}
        if len(pair) == 2:
            a, b = pair["baseline"], pair["candidate"]
            pairs.append(
                {
                    "case": case,
                    "status_before": a["status"],
                    "status_after": b["status"],
                    "same_status_nonfailed": a["status"] == b["status"] != "FAILED",
                    "llm_calls_reduction": a["llm_calls"] - b["llm_calls"],
                    "latency_reduction_s": a["elapsed_s"] - b["elapsed_s"],
                }
            )
    matched = [p for p in pairs if p["same_status_nonfailed"]]
    return {
        "complete": len(rows) == 10,
        "variants": variants,
        "pairs": pairs,
        "same_status_nonfailed_pairs": len(matched),
        "matched_mean_latency_reduction_s": statistics.mean(
            p["latency_reduction_s"] for p in matched
        )
        if matched
        else None,
        "quality": "human review pending; OK/SUPPORTED is not factual correctness",
    }


def run_experiment(plan, modules, baseline, client_factory, service_factory, output):
    from weeing_weeing.contracts import ChatContext, ChatQuestion

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    candidate = {
        filename: {key: getattr(modules[filename], key) for key in values}
        for filename, values in baseline["prompts"].items()
    }
    write_json(
        output / "prompts.json",
        {
            "baseline": baseline["prompts"],
            "candidate": candidate,
        },
    )
    rows = []
    try:
        with (output / "results.jsonl").open("x", encoding="utf-8") as stream:
            for index, case in enumerate(plan["cases"]):
                order = (
                    ("baseline", "candidate")
                    if index % 2 == 0
                    else ("candidate", "baseline")
                )
                for variant in order:
                    prompts = (
                        baseline["prompts"] if variant == "baseline" else candidate
                    )
                    version = plan[variant]
                    with prompt_variant(modules, prompts, version):
                        client = client_factory()
                        tool_turns = []
                        create = client.create

                        def record_create(_create=create, **kwargs):
                            response = _create(**kwargs)
                            tool_turns.append(
                                [
                                    b.name
                                    for b in response.content
                                    if b.type == "tool_use"
                                ]
                            )
                            return response

                        client.create = record_create
                        try:
                            service = service_factory(client)
                            question = ChatQuestion(
                                request_id=uuid4(), question=case["questions"][0]
                            )
                            before = perf_counter()
                            response = service.reply(
                                question,
                                context=ChatContext(),
                                timeout_s=plan["timeout_s"],
                            )
                            elapsed = perf_counter() - before
                            usage = service.last_run
                            if usage is None:
                                raise ValueError("Missing request usage")
                            calls = list(usage.calls)
                            total = usage.total
                            row = {
                                "case": case["id"],
                                "variant": variant,
                                "prompt_version": version,
                                "question": question.question,
                                "request_id": str(question.request_id),
                                "status": response.status,
                                "failure_code": response.failure.code
                                if response.failure
                                else None,
                                "elapsed_s": elapsed,
                                "llm_calls": len(calls),
                                "http_attempts": sum(c.attempts for c in calls),
                                "tool_turns": sum(
                                    c.purpose == "dialogue" for c in calls
                                ),
                                "review_calls": sum(
                                    c.purpose == "grounding" for c in calls
                                ),
                                "turn_tools": tool_turns,
                                "multi_query_turns": sum(
                                    sum(
                                        n
                                        in {
                                            "search_knowledge",
                                            "query_history",
                                            "query_incidents",
                                        }
                                        for n in turn
                                    )
                                    >= 2
                                    for turn in tool_turns
                                ),
                                "usage": dataclasses.asdict(usage),
                                "tokens": dataclasses.asdict(total)
                                if total is not None
                                else None,
                                "response": response.model_dump(mode="json"),
                            }
                            rows.append(row)
                            stream.write(
                                json.dumps(row, ensure_ascii=False, allow_nan=False)
                                + "\n"
                            )
                            stream.flush()
                            print(
                                f"{len(rows)}/10 {case['id']} {variant}: {response.status}, LLM {len(calls)}회",
                                flush=True,
                            )
                            if row["failure_code"] in ABORT_CODES:
                                return rows
                        finally:
                            client.close()
    finally:
        report = summary(rows)
        write_json(output / "summary.json", report)
        write_json(
            output / "quality_review.json",
            [
                {
                    "case": r["case"],
                    "variant": r["variant"],
                    "request_id": r["request_id"],
                    "factual_accuracy_0_2": None,
                    "citation_accuracy_0_2": None,
                    "question_coverage_0_2": None,
                    "scope_accuracy_0_2": None,
                    "critical_error": None,
                    "notes": "",
                }
                for r in rows
            ],
        )
        lines = [
            "# 프롬프트 10요청 비교",
            "",
            "품질은 quality_review.json에서 사람이 확인해야 합니다.",
            "",
            "| 변형 | 요청 | LLM호출 | 작성턴 | 검토호출 | 평균시간(초) | 실패 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for name, r in report["variants"].items():
            latency = (
                f"{r['mean_latency_s']:.3f}"
                if r["mean_latency_s"] is not None
                else "미실행"
            )
            lines.append(
                f"| {name} | {r['requests']} | {r['llm_calls']} | {r['tool_turns']} | {r['review_calls']} | {latency} | {r['failed_requests']} |"
            )
        lines += [
            "",
            f"완료: {report['complete']}. 동일한 비실패 상태 쌍: {report['same_status_nonfailed_pairs']}개.",
            "빠른 실패를 성능 향상으로 해석하지 않습니다. 5문항 1회 결과는 초기 점검입니다.",
        ]
        (output / "comparison.md").write_text("\n".join(lines) + "\n")
    return rows


def catalogue_fingerprint(knowledge):
    """공개 조회 대상의 해시만 보관한다. 운영 문서/보고서 본문은 메타데이터에 쓰지 않는다."""
    data = {
        "documents": sorted(
            (r.model_dump(mode="json") for r in knowledge.documents.listed()),
            key=lambda r: (r["doc_id"], r["doc_version"]),
        ),
        "reports": sorted(
            (r.model_dump(mode="json") for r in knowledge.reports.approved_reports()),
            key=lambda r: (r["report_id"], r["report_version"]),
        ),
    }
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def execute_worker(args, plan):
    from weeing_weeing.agent.interface import get_llm_client
    from weeing_weeing.api.chat_knowledge import build_chat_service, get_chat_knowledge
    from weeing_weeing.config import get_settings
    from weeing_weeing.rag.interface import close_rag_resources

    backend = getattr(args, "backend", "aws-local")
    if backend == "app" and getattr(args, "ask_voyage_key", False):
        if not sys.stdin.isatty():
            raise ValueError("Hidden input requires your terminal")
        key = getpass.getpass("Voyage API 키 (숨김 입력): ").strip()
        if not key:
            raise ValueError("Empty key")
        os.environ["VOYAGE_API_KEY"] = key
        get_settings.cache_clear()
        key = None
    settings = get_settings()
    snapshot = getattr(settings, "search_replica_path", None)
    if backend == "aws-local":
        if not snapshot or settings.qdrant_url != "http://127.0.0.1:16335":
            raise ValueError("AWS local isolated profile required")
        snapshot = Path(snapshot)
        snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    else:
        snapshot = None
        snapshot_hash = None
    if not args.ask_key or not sys.stdin.isatty():
        raise ValueError("--ask-key requires your terminal")
    print("실제 Claude·Voyage 비용이 발생합니다. 키는 파일·채팅에 붙여넣지 마세요.")
    api_key = getpass.getpass("Claude API 키 (숨김 입력): ").strip()
    if not api_key:
        raise ValueError("Empty key")
    modules = {
        name: importlib.import_module("weeing_weeing.agent." + name[:-3])
        for name in ("chat.py", "chat_grounding.py")
    }
    baseline = json.loads(BASELINE_PATH.read_text())
    if not hasattr(modules["chat.py"], "CHAT_PROMPT_VERSION"):
        raise ValueError("Local prompt version support required")
    knowledge = get_chat_knowledge()
    catalogue_hash = catalogue_fingerprint(knowledge) if backend == "app" else None
    started = perf_counter()
    knowledge.retriever  # 동일 조회기를 사전 초기화. 실험 요청 수에는 포함하지 않음.
    warmup_s = perf_counter() - started
    plan = {**plan, "timeout_s": settings.llm_timeout_s}
    output = args.output or ROOT / "outputs/chat_prompt_eval" / datetime.now(
        UTC
    ).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        rows = run_experiment(
            plan,
            modules,
            baseline,
            lambda: get_llm_client(entrypoint="chatbot-prompt-eval", api_key=api_key),
            lambda client: build_chat_service(client=client, knowledge=knowledge),
            output,
        )
        unchanged = (
            hashlib.sha256(snapshot.read_bytes()).hexdigest() == snapshot_hash
            if snapshot
            else catalogue_fingerprint(knowledge) == catalogue_hash
        )
        write_json(
            Path(output) / "metadata.json",
            {
                "client_mode": "same explicit CLI client for writing and review; per-call actual model in results",
                "backend": backend,
                "catalogue_sha256": catalogue_hash,
                "snapshot_sha256": snapshot_hash,
                "snapshot_unchanged": unchanged,
                "warmup_s": warmup_s,
                "reference_time": "actual worker time; five questions have explicit dates or no relative dates",
                "settings": {
                    k: getattr(settings, k, None)
                    for k in [
                        "llm_model",
                        "llm_effort",
                        "llm_timeout_s",
                        "chat_review_model",
                        "chat_review_effort",
                        "embedding_provider",
                        "embedding_model",
                        "reranker_model",
                        "agent_max_turns",
                    ]
                },
                "source_sha256": {
                    str(p.relative_to(ROOT))
                    if p.is_relative_to(ROOT)
                    else p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [
                        ROOT / "scripts/run_chat_prompt_eval.py",
                        CASE_PATH,
                        BASELINE_PATH,
                        *sorted((ROOT / "src/weeing_weeing/agent").glob("*.py")),
                        ROOT / "src/weeing_weeing/api/chat_knowledge.py",
                    ]
                },
            },
        )
        print(f"결과: {output}")
        return (
            0
            if len(rows) == 10
            and unchanged
            and all(r["status"] != "FAILED" for r in rows)
            else 1
        )
    finally:
        api_key = None
        close_rag_resources()
        if backend == "app" and getattr(args, "ask_voyage_key", False):
            os.environ.pop("VOYAGE_API_KEY", None)
            get_settings.cache_clear()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backend", choices=["aws-local", "app"], default="aws-local")
    parser.add_argument("--ask-key", action="store_true")
    parser.add_argument("--ask-voyage-key", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        plan = load_plan()
        if not args.execute:
            print(
                json.dumps(
                    {"mode": "plan_only_no_api_calls", **plan},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.worker or args.backend == "app":
            return execute_worker(args, plan)
        if not args.ask_key:
            raise ValueError("Use --ask-key for hidden Claude key input")
        helper = ROOT / "scripts/aws_local.py"
        if not helper.exists():
            raise ValueError(
                "Run from the local repository containing scripts/aws_local.py"
            )
        subprocess.run(
            [sys.executable, str(helper), "verify"], cwd=ROOT, check=True, timeout=120
        )
        command = [sys.executable, str(helper), "prompt-eval"]
        if args.ask_voyage_key:
            command.append("--ask-voyage-key")
        command += ["--execute", "--worker"]
        if args.ask_key:
            command.append("--ask-key")
        if args.output:
            command += ["--output", str(args.output.resolve())]
        return subprocess.call(command, cwd=ROOT)
    except KeyboardInterrupt:
        print("실험을 중단했습니다. 저장된 부분 결과를 확인하세요.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(
            f"실험 실패: {type(exc).__name__}. AWS local 복사본·키 입력·출력 경로를 확인하세요. 오류 원문은 출력하지 않습니다.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
