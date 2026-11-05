"""#214: AWS의 별도 프로세스에서 배포본/후보본 비교. 기본은 무과금 계획 출력.

--execute는 실제 Claude·Voyage 비용이 발생한다. .env·인증 파일은 읽지 않는다.
서버 파일·컨테이너·HTTP 서비스는 바꾸지 않고 후보 모듈을 프로세스 메모리에만 로드한다.
"""

import argparse
import dataclasses
import hashlib
import importlib
import json
import shlex
import statistics
import subprocess
import sys
import time
import types
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

MODULES = ("chat_usage", "chat_grounding", "chat")
CASES = (
    ("manual", "RPM 저하 시 조치"),
    ("combined", "모터 외함 온도 기준과 과거 과열 조치 이력을 알려줘."),
    ("incidents", "현재 발생 중인 주의와 경고 알림을 알려줘."),
    ("manual_voltage", "DC 버스 저전압이 발생하면 무엇부터 점검해야 해?"),
    ("history_temperature", "모터 외함 과열로 정비했던 이력과 조치 결과를 알려줘."),
    ("history_vibration", "구동측 진동이 커져 정비했던 이력과 조치 결과를 알려줘."),
    ("combined_rpm", "RPM 저하 점검 기준과 과거 RPM 저하 조치 이력을 구분해서 알려줘."),
    ("recovered", "가장 최근 회복된 알림이 무엇인지 알려줘."),
    ("insufficient", "이 설비의 베어링 부품번호와 교체 부품의 재고 수량을 알려줘."),
    ("ambiguous", "그거 어떻게 해야 해?"),
)


def emit(kind, **fields):
    print(json.dumps({"kind": kind, **fields}, ensure_ascii=False), flush=True)


def load_modules(sources):
    for short in MODULES:
        name = f"weeing_weeing.agent.{short}"
        module = types.ModuleType(name)
        module.__file__ = f"<benchmark:{short}>"
        module.__package__ = "weeing_weeing.agent"
        sys.modules[name] = module
        exec(compile(sources[short], module.__file__, "exec"), module.__dict__)


class ProbeTracer:
    def __init__(self, delegate):
        self.delegate = delegate
        self.scores = []
        self.spans = []

    @contextmanager
    def observe(self, name, **kwargs):
        started = time.perf_counter()
        row = {"name": name, "type": kwargs.get("as_type", "span")}
        self.spans.append(row)
        try:
            with self.delegate.observe(name, **kwargs) as observation:
                yield observation
        finally:
            row["elapsed_s"] = time.perf_counter() - started

    def score_trace(self, name, value, **kwargs):
        self.scores.append({"name": name, "value": value})
        method = getattr(self.delegate, "score_trace", None)
        if method:
            method(name, value, **kwargs)

    def flush(self):
        self.delegate.flush()


def worker(repeats, candidates):
    # 이 import들은 --execute 이후 AWS 프로세스에서만 실행한다.
    from weeing_weeing.agent.interface import get_llm_client
    from weeing_weeing.api.chat_knowledge import build_chat_service, get_chat_knowledge
    from weeing_weeing.config import get_settings
    from weeing_weeing.contracts import ChatContext, ChatQuestion
    from weeing_weeing.rag.interface import close_rag_resources

    baseline = {
        short: Path(
            importlib.import_module(f"weeing_weeing.agent.{short}").__file__
        ).read_text()
        for short in MODULES
    }
    settings = get_settings()
    hashes = {
        variant: {k: hashlib.sha256(v.encode()).hexdigest() for k, v in source.items()}
        for variant, source in (("baseline", baseline), ("candidate", candidates))
    }
    knowledge = get_chat_knowledge()
    started = time.perf_counter()
    knowledge.retriever  # 초기화 비용을 양쪽 요청에서 동일하게 제외. LLM 호출 없음.
    warmup_s = time.perf_counter() - started
    emit(
        "environment",
        captured_at=datetime.now(UTC).isoformat(),
        hashes=hashes,
        settings={
            f: getattr(settings, f)
            for f in (
                "llm_model",
                "llm_effort",
                "embedding_model",
                "embedding_provider",
                "embedding_dim",
                "reranker_model",
                "rag_collection",
                "rag_candidate_k",
            )
        },
        warmup_s=warmup_s,
        repeats=repeats,
    )
    try:
        for repeat in range(1, repeats + 1):
            for index, (case, question) in enumerate(CASES):
                order = (
                    ("baseline", "candidate")
                    if (repeat + index) % 2
                    else ("candidate", "baseline")
                )
                for variant in order:
                    load_modules(baseline if variant == "baseline" else candidates)
                    client = get_llm_client(entrypoint=f"chatbot-perf214-{variant}")
                    tracer = ProbeTracer(client.tracer)
                    client.tracer = tracer
                    turns = []
                    create = client.create

                    def record_create(_create=create, **kwargs):
                        response = _create(**kwargs)
                        turns.append(
                            [b.name for b in response.content if b.type == "tool_use"]
                        )
                        return response

                    client.create = record_create
                    try:
                        service = build_chat_service(client=client, knowledge=knowledge)
                        request = ChatQuestion(request_id=uuid4(), question=question)
                        emit("start", variant=variant, case=case, repeat=repeat)
                        started = time.perf_counter()
                        response = service.reply(
                            request,
                            context=ChatContext(),
                            timeout_s=settings.llm_timeout_s,
                        )
                        elapsed = time.perf_counter() - started
                        emit(
                            "result",
                            variant=variant,
                            case=case,
                            question=question,
                            repeat=repeat,
                            request_id=str(request.request_id),
                            elapsed_s=elapsed,
                            status=response.status,
                            failure_code=response.failure.code
                            if response.failure
                            else None,
                            answer_chars=sum(len(p.text) for p in response.parts),
                            sources=[
                                {"kind": s.kind, "id": s.source_id}
                                for s in response.sources
                            ],
                            usage=dataclasses.asdict(service.last_run),
                            turns=turns,
                            scores=tracer.scores,
                            spans=tracer.spans,
                        )
                        if response.failure and response.failure.code in {
                            "LLM_AUTHENTICATION",
                            "RATE_LIMITED",
                            "SEARCH_UNAVAILABLE",
                        }:
                            emit("aborted", reason=response.failure.code)
                            return 2
                    finally:
                        client.close()  # flush/close는 생성 지연 수치에 포함하지 않는다.
    finally:
        close_rag_resources()
    return 0


def summarize(path):
    events = [json.loads(line) for line in path.read_text().splitlines()]
    rows = [r for r in events if r["kind"] == "result"]
    variants = {}
    for variant in ("baseline", "candidate"):
        subset = [r for r in rows if r["variant"] == variant]
        variants[variant] = {
            "requests": len(subset),
            "llm_calls": sum(len(r["usage"]["calls"]) for r in subset),
            "mean_latency_s": statistics.mean(r["elapsed_s"] for r in subset),
            "median_latency_s": statistics.median(r["elapsed_s"] for r in subset),
            "statuses": dict(Counter(r["status"] for r in subset)),
            "multiple_reviews": sum(
                sum(c["purpose"] == "grounding" for c in r["usage"]["calls"]) > 1
                for r in subset
            ),
        }
    pairs = {(r["case"], r["repeat"], r["variant"]): r for r in rows}
    status_changes = []
    matched = []
    for case, _ in CASES:
        for repeat in sorted({r["repeat"] for r in rows if r["case"] == case}):
            before = pairs.get((case, repeat, "baseline"))
            after = pairs.get((case, repeat, "candidate"))
            if before and after and before["status"] == after["status"] != "FAILED":
                matched.append((before, after))
            if before and after and before["status"] != after["status"]:
                status_changes.append(
                    {
                        "case": case,
                        "repeat": repeat,
                        "before": before["status"],
                        "after": after["status"],
                    }
                )
    summary = {
        "variants": variants,
        "status_changes": status_changes,
        "reductions": {
            "llm_calls": variants["baseline"]["llm_calls"]
            - variants["candidate"]["llm_calls"],
            "llm_calls_percent": 100
            * (
                1
                - variants["candidate"]["llm_calls"] / variants["baseline"]["llm_calls"]
            ),
            "mean_latency_s": variants["baseline"]["mean_latency_s"]
            - variants["candidate"]["mean_latency_s"],
            "mean_latency_percent": 100
            * (
                1
                - variants["candidate"]["mean_latency_s"]
                / variants["baseline"]["mean_latency_s"]
            ),
        },
        "same_status_nonfailed_pairs": {
            "pairs": len(matched),
            "baseline_mean_latency_s": statistics.mean(
                a["elapsed_s"] for a, _ in matched
            )
            if matched
            else None,
            "candidate_mean_latency_s": statistics.mean(
                b["elapsed_s"] for _, b in matched
            )
            if matched
            else None,
            "baseline_llm_calls": sum(len(a["usage"]["calls"]) for a, _ in matched),
            "candidate_llm_calls": sum(len(b["usage"]["calls"]) for _, b in matched),
        },
        "complete": not any(e["kind"] == "aborted" for e in events)
        and len(pairs) == len(rows)
        and all(
            v["requests"] == len(CASES) * events[0]["repeats"]
            for v in variants.values()
        ),
    }
    path.with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    lines = [
        "# 챗봇 LLM 왕복 개선 비교",
        "",
        "| 질문 | LLM 평균 호출 전→후 | 지연 중앙값 전→후(초) | 상태 전→후 |",
        "|---|---:|---:|---|",
    ]
    for case, question in CASES:
        cols = []
        for variant in ("baseline", "candidate"):
            subset = [r for r in rows if r["case"] == case and r["variant"] == variant]
            cols.append(
                (
                    statistics.mean(len(r["usage"]["calls"]) for r in subset),
                    statistics.median(r["elapsed_s"] for r in subset),
                    dict(Counter(r["status"] for r in subset)),
                )
            )
        a, b = cols
        lines.append(
            f"| {question} | {a[0]:.1f} → {b[0]:.1f} | {a[1]:.2f} → {b[1]:.2f} | {a[2]} → {b[2]} |"
        )
    lines += [
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "같은 AWS의 별도 측정 프로세스에서 배포본/후보본을 번갈아 실행했다. 각 요청은 빈 문맥·새 Claude 클라이언트이며 검색기는 공통으로 사전 초기화했다.",
        "시간 범위는 서비스 reply 진입~반환이며 HTTP 인증·대화 저장·SSE·브라우저 표시와 trace flush/close를 제외한다. 운영 트래픽을 통제한 부하 시험이 아니다.",
        "상태·인용 형식·모델 검토 통과는 사실 정확성의 사람 검수를 대신하지 않는다. 서로 다른 상태로 끝난 쌍은 동등한 답변의 속도 향상으로 해석하지 않는다.",
        "요청 수는 사용자 질문 수와 LLM 호출 수를 구분한다. 원시 JSONL에는 응답 본문·키가 없으며, 호출별 시간·토큰·턴별 도구·검토 메타데이터가 들어 있다.",
        "",
    ]
    path.with_suffix(".md").write_text("\n".join(lines))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="실제 유료 API 평가 실행"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=2)
    parser.add_argument("--ssh-host", default="ww-team")
    parser.add_argument("--container", default="weeing-weeing-api-1")
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/chat_roundtrips/comparison.jsonl")
    )
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args.repeats, globals()["CANDIDATE_SOURCES"])
    if not args.execute:
        print(
            json.dumps(
                {
                    "questions": len(CASES),
                    "repeats": args.repeats,
                    "service_requests": len(CASES) * args.repeats * 2,
                    "execute": False,
                },
                indent=2,
            )
        )
        return 0
    if args.ssh_host.startswith("-") or args.container.startswith("-"):
        parser.error("SSH 별칭과 컨테이너 이름은 '-'로 시작할 수 없습니다.")
    root = Path(__file__).resolve().parents[1]
    candidates = {
        short: (root / f"src/weeing_weeing/agent/{short}.py").read_text()
        for short in MODULES
    }
    payload = (
        f"CANDIDATE_SOURCES = {candidates!r}\n"
        f"import sys; sys.argv = ['benchmark', '--worker', '--repeats', {str(args.repeats)!r}]\n"
        + Path(__file__).read_text()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    remote = shlex.join(["docker", "exec", "-i", args.container, "python", "-u", "-"])
    # 결과 덮어쓰기 금지. SSH 자격증명·환경변수는 읽거나 출력하지 않는다.
    with (
        args.output.open("x") as output,
        args.output.with_suffix(".stderr.log").open("x") as errors,
    ):
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                args.ssh_host,
                remote,
            ],
            input=payload,
            text=True,
            stdout=output,
            stderr=errors,
            timeout=2400,
            check=False,
        )
    if result.returncode:
        print(f"측정 중단(exit={result.returncode}): {args.output}", file=sys.stderr)
        return result.returncode
    print(json.dumps(summarize(args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
