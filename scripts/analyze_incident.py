"""사건 하나를 사건 분석 에이전트로 분석한다 (#102, make analyze).

Claude가 근거 검색 도구를 골라 부르고 원인 후보를 제출한다. 결과는 AnalysisResult JSON과
도구 호출 기록이다. 기본은 DB 미저장이며 --save-db로 기존 사건에 결과만 저장한다.

입력: --incident Incident JSON 파일(기본 data/eval/incident_p03_demo.json),
      .env(ANTHROPIC_API_KEY·LLM_MODEL·LLM_EFFORT·AGENT_MAX_TURNS), 웹에서 문서를 등록한 벡터 DB
      LANGFUSE_* 설정이 있으면 사용량이 Langfuse에 남는다(태그 analyze)
--sensor-window: DB 센서 구간 조회·수치 검증 도구도 제공한다(#105, Claude 유료 호출).
출력: 터미널에 결과 JSON·도구 호출·토큰 수
종료 코드: 0 OK 또는 INSUFFICIENT_EVIDENCE / 1 FAILED / 2 입력·설정 문제로 시작 못 함

    make analyze
    make analyze ARGS="--incident 사건.json"
"""

import argparse
import getpass
import hashlib
import json
import sys
import time
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError

from weeing_weeing.agent.interface import SensorBatch, get_analyzer, get_llm_client
from weeing_weeing.config import PROJECT_ROOT, get_settings
from weeing_weeing.contracts import Incident
from weeing_weeing.db import interface as db
from weeing_weeing.rag.interface import close_rag_resources, get_retriever

DEMO = PROJECT_ROOT / "data/eval/incident_p03_demo.json"


def evaluation_summary(result, memory, *, elapsed_s, flush_s, minimum):
    """평가 지표만 반환한다. 도구 입력·요청·근거 원문은 포함하지 않는다."""
    calls = memory.tool_calls if memory is not None else []
    submissions = [c for c in calls if c.name == "submit_analysis" and c.ok]
    claims = submissions[-1].input.get("sensor_claims", []) if submissions else []
    cited = {i for c in result.suspected_causes for i in c.evidence_ids}
    known = set(memory.evidence) if memory is not None else None
    return {
        "incident_id": result.incident_id,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "status": result.status,
        "agent_wall_seconds": elapsed_s,
        "trace_flush_seconds": flush_s,
        "min_relevance": minimum,
        "llm_calls": memory.turns if memory is not None else None,
        "tool_calls": [{"name": c.name, "ok": c.ok} for c in calls],
        "citation_ids_valid": not (cited - known) if known is not None else None,
        "cited_evidence_count": len(cited),
        "retrieved_evidence_count": len(known) if known is not None else None,
        "retrieved_relevance": [e.relevance for e in memory.evidence.values()]
        if memory is not None
        else [],
        "sensor_queries": sum(c.name == "get_sensor_window" and c.ok for c in calls),
        "validated_sensor_claims": len(claims),
        "usage": asdict(memory.usage) if memory is not None else None,
        "note": "ID 대조는 인용 내용의 의미 검증이 아니다. 센서 조회·제출 수치가 없으면 수치 검증 경로를 시험한 것이 아니다.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--incident", type=Path, default=DEMO)
    parser.add_argument(
        "--ask-key", action="store_true", help="본인 터미널에서 API 키 숨김 입력"
    )
    parser.add_argument(
        "--result-out", type=Path, help="결과 JSON. 기존 파일은 덮어쓰지 않음"
    )
    parser.add_argument(
        "--save-db",
        action="store_true",
        help="현재 DB의 같은 사건에 분석만 저장. --result-out 필수",
    )
    parser.add_argument(
        "--evaluation-out",
        type=Path,
        help="실측 지표 JSON 경로. 기존 파일은 덮어쓰지 않음",
    )
    parser.add_argument(
        "--sensor-window",
        action="store_true",
        help="현재 DB의 사건 센서 구간 조회 도구를 제공한다(Claude 유료 호출)",
    )
    args = parser.parse_args(argv)
    if args.save_db and not args.result_out:
        parser.error("--save-db에는 호출 후 결과를 보존할 --result-out이 필요합니다.")
    if args.ask_key and not sys.stdin.isatty():
        parser.error("--ask-key는 사용자가 직접 연 일반 터미널에서 실행하세요.")

    try:
        if args.result_out:
            if args.result_out.exists():
                raise ValueError(
                    "분석 결과 파일이 이미 있습니다. 유료 호출을 반복하지 않습니다."
                )
            if (
                args.evaluation_out
                and args.result_out.resolve() == args.evaluation_out.resolve()
            ):
                raise ValueError("결과 파일과 평가 지표 파일은 달라야 합니다.")
            args.result_out.parent.mkdir(parents=True, exist_ok=True)
        if args.evaluation_out:
            if args.evaluation_out.exists():
                raise ValueError("평가 결과 파일이 이미 있다")
            args.evaluation_out.parent.mkdir(parents=True, exist_ok=True)
        incident_bytes = args.incident.read_bytes()
        incident = Incident.model_validate_json(incident_bytes)
        result_repository = None
        if args.save_db:
            result_repository = db.get_analysis_jobs()
            saved = result_repository.get_incident(incident.incident_id)
            if saved is None or (saved.process_id, saved.asset_id) != (
                incident.process_id,
                incident.asset_id,
            ):
                raise ValueError("DB에 같은 공정·설비의 사건이 없습니다.")
            job = result_repository.latest_job(incident.incident_id)
            if job and job["status"] in ("PENDING", "RUNNING"):
                raise ValueError("대기 또는 실행 중인 분석이 있습니다.")
        reader = None
        if args.sensor_window:
            repository = db.get_telemetry()

            def reader(item, start, end, *, limit):
                latest = repository.latest(item.asset_id, process_id=item.process_id)
                if latest is None or latest.timestamp < start:
                    return SensorBatch([], latest.timestamp if latest else None)
                observations = repository.observations_between(
                    item.asset_id,
                    start,
                    min(end, latest.timestamp + timedelta(microseconds=1)),
                    process_id=item.process_id,
                    limit=limit,
                )
                return SensorBatch(
                    [row for row, _ in observations],
                    latest.timestamp,
                    {
                        row.timestamp: source
                        for row, source in observations
                        if source is not None
                    },
                )

        api_key = None
        if args.ask_key:
            api_key = getpass.getpass(
                "Claude API 키 (숨김; 실제 API 비용 발생): "
            ).strip()
            if not api_key:
                print("API 키가 입력되지 않았습니다.", file=sys.stderr)
                return 2
        client = get_llm_client(entrypoint="analyze", api_key=api_key)
        api_key = None
        analyzer = get_analyzer(
            get_retriever(), client=client, sensor_reader=reader, mode="single"
        )
    except (OSError, ValidationError, ValueError, db.DatabaseUnavailableError) as exc:
        print(f"시작하지 못함: {exc}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    if args.evaluation_out:
        print(
            f"[Agent 평가 시작] incident={incident.incident_id} sensor_window={args.sensor_window}",
            flush=True,
        )
    result = analyzer.analyze(incident)
    elapsed = time.perf_counter() - started
    if args.result_out or args.save_db:
        if result.incident_id != incident.incident_id:
            print("분석 사건 ID가 입력과 다릅니다. 저장하지 않습니다.", file=sys.stderr)
            return 2
        try:
            if args.result_out:
                with args.result_out.open("x", encoding="utf-8") as file:
                    file.write(result.model_dump_json(indent=2))
            if result_repository is not None:
                analysis_id = result_repository.save_analysis_with_input(
                    result, incident
                )
                print(
                    f"[단건 분석 저장] incident={incident.incident_id} analysis={analysis_id}"
                )
        except (
            OSError,
            db.DatabaseUnavailableError,
            db.UnknownIncidentError,
            db.AnalysisConflictError,
        ) as exc:
            print(
                f"분석 저장 실패: {type(exc).__name__}. 결과 파일을 확인하세요. "
                "유료 분석을 자동 재실행하지 않습니다.",
                file=sys.stderr,
            )
            return 2
    flush_started = time.perf_counter()
    client.tracer.flush()  # 짧은 스크립트라 끝나기 전에 기록을 보낸다
    flush_seconds = time.perf_counter() - flush_started
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
    if args.evaluation_out:
        try:
            summary = evaluation_summary(
                result,
                memory,
                elapsed_s=elapsed,
                flush_s=flush_seconds,
                minimum=get_settings().rag_min_relevance,
            )
            summary["incident_sha256"] = hashlib.sha256(incident_bytes).hexdigest()
            with args.evaluation_out.open("x", encoding="utf-8") as file:
                json.dump(summary, file, ensure_ascii=False, indent=2)
            print(f"평가 지표: {args.evaluation_out}")
        except OSError as exc:
            print(
                f"평가 지표 저장 실패: {type(exc).__name__}. 분석을 자동 재실행하지 않습니다.",
                file=sys.stderr,
            )
            return 2
    return 1 if result.status == "FAILED" else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        close_rag_resources()
