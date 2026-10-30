"""터미널 대화·키 숨김 입력·문맥 상한. 실제 키·SDK·DB·네트워크를 사용하지 않는다."""

import runpy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from weeing_weeing.contracts import (
    ChatContext,
    ChatDocumentSource,
    ChatQuestion,
    ChatResponse,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/chat.py"


def response(question):
    return ChatResponse(
        request_id=question.request_id,
        intent="MANUAL",
        status="INSUFFICIENT_EVIDENCE",
        applied_conditions=question.conditions,
        message="근거가 부족합니다.",
        generated_at=datetime.now(UTC),
    )


@pytest.fixture
def cli(monkeypatch):
    main = runpy.run_path(str(SCRIPT))["main"]
    namespace = main.__globals__
    calls = []
    keys = []
    closed = []

    class Service:
        last_run = None

        def reply(self, question, *, context, timeout_s):
            calls.append((question, context))
            return response(question)

    def client(**kwargs):
        keys.append(kwargs.get("api_key"))
        return SimpleNamespace(close=lambda: closed.append("client"))

    monkeypatch.setitem(namespace, "get_llm_client", client)
    monkeypatch.setitem(namespace, "build_chat_service", lambda **_: Service())
    monkeypatch.setitem(namespace, "close_rag_resources", lambda: closed.append("rag"))
    return main, namespace, calls, keys, closed


@pytest.mark.parametrize("with_stats", [False, True])
def test_interactive_context_and_reset_are_local_and_key_is_not_printed(
    cli, monkeypatch, capsys, with_stats
):
    main, namespace, calls, keys, closed = cli
    monkeypatch.setattr(namespace["sys"].stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        namespace["getpass"], "getpass", lambda _: "FAKE_SECRET_SENTINEL"
    )
    questions = iter(["첫 질문", "두 번째 질문", "/reset", "세 번째 질문", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(questions))
    diagnostics = []
    monkeypatch.setitem(
        namespace, "show_usage", lambda *a, **k: diagnostics.append(k["stream"])
    )
    args = ["--interactive", "--ask-key", "--asset-id", "BLDC-001"]
    if with_stats:
        args.append("--stats")
    assert main(args) == 0
    assert diagnostics == ([namespace["sys"].stderr] * 3 if with_stats else [])
    assert [len(context.recent_turns) for _, context in calls] == [0, 2, 0]
    assert all(q.conditions.asset_id == "BLDC-001" for q, _ in calls)
    assert keys == ["FAKE_SECRET_SENTINEL"]
    assert closed == ["client", "rag"]
    captured = capsys.readouterr()
    assert "FAKE_SECRET_SENTINEL" not in captured.out + captured.err


def test_key_prompt_refuses_non_tty_before_creating_client(cli, monkeypatch):
    main, namespace, _, keys, _ = cli
    monkeypatch.setattr(namespace["sys"].stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit) as error:
        main(["--ask-key", "질문"])
    assert error.value.code == 2 and keys == []


def test_single_question_remains_json_and_failures_do_not_dump_provider_details(
    cli, monkeypatch, capsys
):
    main, namespace, calls, _, _ = cli
    assert main(["점검 방법"]) == 0
    assert '"status": "INSUFFICIENT_EVIDENCE"' in capsys.readouterr().out
    assert not calls[0][1].recent_turns

    def fail(**_):
        raise RuntimeError("FAKE_PRIVATE_ERROR_SENTINEL")

    monkeypatch.setitem(namespace, "build_chat_service", fail)
    assert main(["점검 방법"]) == 2
    captured = capsys.readouterr()
    assert "FAKE_PRIVATE_ERROR_SENTINEL" not in captured.out + captured.err


def test_recent_conversation_stays_within_contract_bounds():
    remember = runpy.run_path(str(SCRIPT))["remember"]
    context = ChatContext()
    for _ in range(30):
        question = ChatQuestion(request_id=uuid4(), question="질문" * 900)
        answer = response(question).model_copy(update={"message": "안내" * 2000})
        context = remember(context, question, answer)
        assert len(context.recent_turns) <= 20
        assert sum(len(turn.content) for turn in context.recent_turns) <= 16000
        assert len(context.recent_turns) % 2 == 0


@pytest.mark.parametrize(
    ("locations", "expected_sources"),
    [
        ([{"page": 5}, {"page": 5}], 1),
        ([{"page": 5, "section": "1"}, {"page": 5, "section": "2"}], 1),
        ([{"page": 5}, {"page": 6}], 2),
        ([{"section": "1"}, {"section": "2"}], 2),
    ],
)
def test_show_deduplicates_displayed_location_and_preserves_other_sources(
    capsys, locations, expected_sources
):
    show = runpy.run_path(str(SCRIPT))["show"]
    question = ChatQuestion(request_id=uuid4(), question="질문")
    source_fields = {
        "title": "BTT-MANUAL_v2.0.pdf",
        "doc_id": "BLDC-001-MANUAL",
        "doc_version": "v2.0",
    }
    response_value = ChatResponse(
        request_id=question.request_id,
        intent="MANUAL",
        status="OK",
        applied_conditions=question.conditions,
        message="안내합니다.",
        parts=[
            {
                "kind": "MANUAL",
                "text": "첫 번째 근거",
                "source_ids": ["chunk-1"],
            },
            {
                "kind": "MANUAL",
                "text": "두 번째 근거",
                "source_ids": ["chunk-2"],
            },
        ],
        sources=[
            ChatDocumentSource(source_id="chunk-1", **source_fields, **locations[0]),
            ChatDocumentSource(source_id="chunk-2", **source_fields, **locations[1]),
        ],
        generated_at=datetime.now(UTC),
    )

    show(response_value)

    assert capsys.readouterr().out.count("출처:") == expected_sources
