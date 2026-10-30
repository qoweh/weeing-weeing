"""#106 실제 Agent 평가 지표 저장. 유료 호출·DB 없이 검사한다."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from weeing_weeing.agent.errors import LlmUsage
from weeing_weeing.agent.tracing import NULL_TRACER
from weeing_weeing.contracts import AnalysisResult

ROOT = Path(__file__).resolve().parents[2]


def script():
    spec = importlib.util.spec_from_file_location(
        "analyze_evaluation", ROOT / "scripts/analyze_incident.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metrics_are_saved_without_tool_inputs_or_raw_facts(tmp_path, monkeypatch):
    module = script()
    result = AnalysisResult(
        incident_id="test",
        status="INSUFFICIENT_EVIDENCE",
        observed_facts="PRIVATE_FACT",
        model="fake/model",
        generated_at=datetime.now(UTC),
    )
    memory = SimpleNamespace(
        turns=2,
        evidence={},
        usage=LlmUsage(10, 20, 0.3, 2, 3),
        tool_calls=[
            SimpleNamespace(
                name="get_sensor_window", ok=True, input={"private": "PRIVATE_TOOL"}
            ),
            SimpleNamespace(
                name="submit_analysis",
                ok=True,
                input={"sensor_claims": [{"private": "PRIVATE_TOOL"}]},
            ),
        ],
    )
    analyzer = SimpleNamespace(last_memory=memory, analyze=lambda item: result)
    monkeypatch.setattr(module, "get_analyzer", lambda *a, **kw: analyzer)
    monkeypatch.setattr(
        module, "get_llm_client", lambda **kw: SimpleNamespace(tracer=NULL_TRACER)
    )
    monkeypatch.setattr(module, "get_retriever", lambda: object())
    output = tmp_path / "metrics.json"
    assert module.main(["--evaluation-out", str(output)]) == 0
    raw = output.read_text("utf-8")
    data = json.loads(raw)
    assert (
        data["llm_calls"] == 2
        and data["sensor_queries"] == data["validated_sensor_claims"] == 1
    )
    assert data["usage"]["cache_read_input_tokens"] == 2
    assert "PRIVATE" not in raw and len(data["incident_sha256"]) == 64


def test_existing_metrics_path_rejected_before_api(tmp_path, monkeypatch):
    module = script()
    output = tmp_path / "metrics.json"
    output.write_text("keep", encoding="utf-8")

    def forbidden(**kw):
        raise AssertionError("API factory must not be called")

    monkeypatch.setattr(module, "get_llm_client", forbidden)
    assert module.main(["--evaluation-out", str(output)]) == 2
    assert output.read_text("utf-8") == "keep"
