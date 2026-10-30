"""#106 비교 실행의 무과금 기본값·호출 상한·중간 저장·개인정보 제외."""

import importlib.util
import json
from pathlib import Path

import pytest

from weeing_weeing.agent.interface import (
    LlmModelMissingError,
    LlmRequestError,
    LlmUsage,
)
from weeing_weeing.agent.tracing import NULL_TRACER

ROOT = Path(__file__).resolve().parents[2]


def script():
    spec = importlib.util.spec_from_file_location(
        "compare_llm", ROOT / "scripts/compare_llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def response():
    return json.dumps(
        {
            "observed_facts": "PRIVATE_RESPONSE",
            "suspected_causes": [],
            "status": "INSUFFICIENT_EVIDENCE",
        }
    )


class FakeClient:
    model_name = "fake"
    provider = "fake"
    tracer = NULL_TRACER
    last_usage = None

    def __init__(self, answers):
        self.answers = iter(answers)
        self.calls = 0

    def generate_json(self, *args, **kwargs):
        self.calls += 1
        value = next(self.answers)
        if isinstance(value, BaseException):
            raise value
        self.last_usage = LlmUsage(10, 5, 1, 3, 4)
        return value


@pytest.fixture
def setup(tmp_path):
    cases = tmp_path / "cases.toml"
    cases.write_text(
        '[[cases]]\nid="a"\nincident="PRIVATE_REQUEST"\nexpected_status="INSUFFICIENT_EVIDENCE"\nexpected_evidence_ids=[]\n',
        encoding="utf-8",
    )
    output = tmp_path / "result"
    return script(), cases, output


def test_dry_run_never_constructs_client(setup, monkeypatch, capsys):
    module, cases, output = setup
    monkeypatch.setattr(
        module, "get_llm_client", lambda *a, **k: pytest.fail("유료 경계 호출")
    )
    assert module.main(["--cases", str(cases), "--out", str(output)]) == 0
    assert not output.exists()
    assert "PRIVATE_REQUEST" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        ["--max-calls", "1"],
        ["--setting", "x:low", "--setting", "x:low"],
        ["--case-id", "absent"],
    ],
)
def test_bad_plan_stops_before_client(setup, monkeypatch, extra):
    module, cases, output = setup
    monkeypatch.setattr(
        module, "get_llm_client", lambda *a, **k: pytest.fail("유료 경계 호출")
    )
    assert (
        module.main(["--cases", str(cases), "--out", str(output), "--execute", *extra])
        == 2
    )
    assert not output.exists()


def test_results_have_setting_cache_usage_and_no_raw_content(setup, monkeypatch):
    module, cases, output = setup
    clients = []

    def factory(settings, **kwargs):
        client = FakeClient([response()] * 2)
        client.model_name = settings.llm_model
        clients.append(client)
        return client

    monkeypatch.setattr(module, "get_llm_client", factory)
    args = [
        "--cases",
        str(cases),
        "--out",
        str(output),
        "--execute",
        "--repeat",
        "2",
        "--setting",
        "one:low",
        "--setting",
        "two:medium",
    ]
    assert module.main(args) == 0
    result = json.loads((output / "results.json").read_text("utf-8"))
    assert result["plan"]["planned_calls"] == 4
    assert [r["effort"] for r in result["reports"]] == ["low", "medium"]
    assert all(
        r["passed"] and r["cache_read_input_tokens"] == 6 for r in result["reports"]
    )
    assert sum(c.calls for c in clients) == 4
    for path in output.iterdir():
        assert "PRIVATE_REQUEST" not in path.read_text("utf-8")
        assert "PRIVATE_RESPONSE" not in path.read_text("utf-8")
    assert module.main(args) == 2  # 기존 결과를 덮어쓰지 않는다.
    assert sum(c.calls for c in clients) == 4


@pytest.mark.parametrize(
    "failure", [LlmModelMissingError("private error details"), KeyboardInterrupt()]
)
def test_stop_preserves_completed_results_without_extra_calls(
    setup, monkeypatch, failure
):
    module, cases, output = setup
    client = FakeClient([response(), failure])
    monkeypatch.setattr(module, "get_llm_client", lambda *a, **k: client)
    assert (
        module.main(
            [
                "--cases",
                str(cases),
                "--out",
                str(output),
                "--execute",
                "--repeat",
                "3",
                "--setting",
                "one:low",
            ]
        )
        == 2
    )
    report = json.loads((output / "results.json").read_text("utf-8"))["reports"][0]
    assert report["completed_runs"] == 1 and report["planned_runs"] == 3
    assert not report["passed"] and client.calls == 2
    assert "private error details" not in (output / "results.json").read_text("utf-8")


def test_http_limit_stops_batch_at_first_request(setup, monkeypatch):
    module, cases, output = setup
    client = FakeClient([LlmRequestError(429)])
    monkeypatch.setattr(module, "get_llm_client", lambda *a, **k: client)
    assert (
        module.main(
            [
                "--cases",
                str(cases),
                "--out",
                str(output),
                "--execute",
                "--repeat",
                "3",
                "--setting",
                "one:medium",
                "--setting",
                "two:low",
            ]
        )
        == 2
    )
    data = json.loads((output / "results.json").read_text("utf-8"))
    assert client.calls == 1 and len(data["reports"]) == 1
    assert data["plan"]["termination"]["http_status"] == 429
    assert data["reports"][0]["completed_runs"] == 0
