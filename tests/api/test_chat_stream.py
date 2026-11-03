"""초안 차단·저장 실패·연결 종료를 실제 LLM 없이 스트림 경계에서 검증한다."""

import asyncio
import json
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

from weeing_weeing.api.chat_stream import _active, stream_chat
from weeing_weeing.contracts.chat_storage import ChatRequestView


def view(request_id):
    now = datetime.now(UTC)
    return ChatRequestView(
        conversation_id=uuid4(),
        submission=dict(kind="CHAT", request_id=request_id, question="현재 알림"),
        state="COMPLETED",
        conditions={},
        response=dict(
            request_id=request_id,
            intent="MANUAL",
            status="OK",
            applied_conditions={},
            message="안내",
            parts=[
                dict(
                    kind="MANUAL",
                    text="## 검증 완료\n\n**센서** 점검",
                    source_ids=["doc:1"],
                )
            ],
            sources=[
                dict(
                    kind="DOCUMENT",
                    source_id="doc:1",
                    title="매뉴얼",
                    doc_id="MAN",
                    doc_version="1",
                    page=1,
                )
            ],
            generated_at=now,
        ),
        created_at=now,
        updated_at=now,
    )


def data(frame):
    return json.loads(
        next(line[6:] for line in frame.splitlines() if line.startswith("data: "))
    )


def test_before_validation_only_progress_and_after_save_exact_answer():
    async def scenario():
        request_id = uuid4()
        release = Event()
        saved = view(request_id)

        def execute(progress):
            progress("searching")
            progress("verifying")
            assert release.wait(3)
            progress("saving")
            return saved

        stream = stream_chat(request_id, execute)
        try:
            assert data(await anext(stream))["phase"] == "accepted"
            first = data(await anext(stream))
            second = data(await anext(stream))
            assert [first["phase"], second["phase"]] == ["searching", "verifying"]
            assert all(
                e["event"] == "progress" and "text" not in e for e in (first, second)
            )
            release.set()
            events = [data(frame) async for frame in stream]
            assert events[-1]["request"]["state"] == "COMPLETED"
            assert (
                "".join(e["text"] for e in events if e["event"] == "delta")
                == saved.response.parts[0].text
            )
        finally:
            release.set()
            await stream.aclose()

    asyncio.run(scenario())


def test_disconnect_does_not_cancel_execution_or_save():
    async def scenario():
        request_id = uuid4()
        entered, release, finished = Event(), Event(), Event()

        def execute(progress):
            entered.set()
            assert release.wait(3)
            progress("saving")
            finished.set()
            return view(request_id)

        stream = stream_chat(request_id, execute)
        await anext(stream)
        assert await asyncio.to_thread(entered.wait, 2)
        await stream.aclose()
        release.set()
        await asyncio.gather(*list(_active))
        assert finished.is_set()

    asyncio.run(scenario())


def test_storage_failure_never_publishes_a_draft_or_exception_body():
    from weeing_weeing.db.interface import DatabaseUnavailableError

    async def scenario():
        def execute(progress):
            progress("saving")
            raise DatabaseUnavailableError("FAKE_PRIVATE_ERROR")

        frames = [frame async for frame in stream_chat(uuid4(), execute)]
        events = [data(frame) for frame in frames]
        assert events[-1]["event"] == "error" and events[-1]["status_code"] == 503
        assert not any(e["event"] == "delta" for e in events)
        assert "FAKE_PRIVATE_ERROR" not in "".join(frames)

    asyncio.run(scenario())
