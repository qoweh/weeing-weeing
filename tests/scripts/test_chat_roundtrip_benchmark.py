"""실제 SSH·LLM 없이 비교 계획과 집계의 의미를 검증한다."""

import importlib.util
import json
from pathlib import Path


def module():
    path = Path(__file__).resolve().parents[2] / "scripts/benchmark_chat_roundtrips.py"
    spec = importlib.util.spec_from_file_location("roundtrip_benchmark", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_default_only_prints_plan_and_never_connects(monkeypatch, capsys):
    benchmark = module()

    def forbidden(*args, **kwargs):
        raise AssertionError("기본 실행은 외부 연결을 하면 안 된다")

    monkeypatch.setattr(benchmark.subprocess, "run", forbidden)
    assert benchmark.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "questions": 10,
        "repeats": 2,
        "service_requests": 40,
        "execute": False,
    }


def test_summary_separates_llm_count_latency_and_status_regressions(tmp_path):
    benchmark = module()
    benchmark.CASES = (("manual", "매뉴얼 질문"), ("ambiguous", "모호한 질문"))
    rows = [{"kind": "environment", "repeats": 1}]
    for case, _ in benchmark.CASES:
        for variant in ("baseline", "candidate"):
            before = variant == "baseline"
            rows.append(
                {
                    "kind": "result",
                    "case": case,
                    "repeat": 1,
                    "variant": variant,
                    "elapsed_s": 20 if before else 10,
                    "status": "FAILED" if case == "manual" and not before else "OK",
                    "usage": {
                        "calls": [{"purpose": "dialogue"}] * (5 if before else 3)
                    },
                }
            )
    path = tmp_path / "comparison.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    summary = benchmark.summarize(path)
    assert summary["complete"]
    assert summary["variants"]["baseline"]["llm_calls"] == 10
    assert summary["variants"]["candidate"]["llm_calls"] == 6
    assert summary["variants"]["candidate"]["median_latency_s"] == 10
    assert summary["reductions"]["llm_calls"] == 4
    assert summary["reductions"]["mean_latency_percent"] == 50
    assert summary["same_status_nonfailed_pairs"]["pairs"] == 1
    assert summary["status_changes"] == [
        {
            "case": "manual",
            "repeat": 1,
            "before": "OK",
            "after": "FAILED",
        }
    ]
    assert "동등한 답변" in path.with_suffix(".md").read_text()
