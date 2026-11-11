"""SSE 전송: 진행 상태는 즉시, 답변 본문은 검증·DB 저장 완료 뒤에만 공개한다."""

import asyncio
from collections.abc import Callable

from fastapi import HTTPException

from weeing_weeing.contracts.chat_storage import ChatRequestView
from weeing_weeing.contracts.chat_stream import (
    ChatPhase,
    ChatProgress,
    ChatStreamDelta,
    ChatStreamDone,
    ChatStreamError,
    ChatStreamProgress,
)
from weeing_weeing.db.interface import DatabaseUnavailableError

# 연결이 끊겨도 이미 시작한 요청의 저장을 마치도록 작업 참조를 유지한다.
_active: set[asyncio.Task] = set()


def _frame(event) -> str:
    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"


def _finished(task):
    _active.discard(task)
    if not task.cancelled():
        task.exception()  # 연결 종료 후의 예외도 수거한다. 원문은 로그에 남기지 않는다.


async def stream_chat(request_id, operation: Callable[[ChatProgress], ChatRequestView]):
    """재생용 지연 없이 검증된 마크다운을 조각으로 전송한다. 재접속은 GET 조회다."""
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=64)
    connected = True
    reserved = False

    def offer(phase: ChatPhase):
        if connected and not queue.full():
            queue.put_nowait(ChatStreamProgress(request_id=request_id, phase=phase))

    def progress(phase: ChatPhase):
        nonlocal reserved
        if phase == "accepted":
            reserved = True
        try:
            loop.call_soon_threadsafe(offer, phase)
        except RuntimeError:
            pass  # 서버 종료/전송 종료가 생성 결과 저장을 방해해서는 안 된다.

    task = asyncio.create_task(asyncio.to_thread(operation, progress))
    _active.add(task)
    task.add_done_callback(_finished)
    try:
        yield _frame(ChatStreamProgress(request_id=request_id, phase="accepted"))
        previous = "accepted"
        while not task.done() or not queue.empty():
            if not queue.empty():
                event = queue.get_nowait()
                if event.phase != previous:
                    yield _frame(event)
                    previous = event.phase
                continue
            next_event = asyncio.create_task(queue.get())
            try:
                ready, _ = await asyncio.wait(
                    {task, next_event}, timeout=10, return_when=asyncio.FIRST_COMPLETED
                )
                if next_event in ready:
                    event = next_event.result()
                    if event.phase != previous:
                        yield _frame(event)
                        previous = event.phase
                elif not ready:
                    yield ": keep-alive\n\n"
            finally:
                if not next_event.done():
                    next_event.cancel()
                    await asyncio.gather(next_event, return_exceptions=True)
        result = task.result()
        if result.cache_hit:
            yield _frame(ChatStreamProgress(request_id=request_id, phase="cache_hit"))
        if result.state == "COMPLETED" and result.response.status == "OK":
            text = "\n\n".join(part.text for part in result.response.parts)
            for start in range(0, len(text), 512):
                yield _frame(
                    ChatStreamDelta(
                        request_id=request_id, text=text[start : start + 512]
                    )
                )
        # 상태·본문·출처의 기준은 DB 저장 완료 응답이다. 초안은 이벤트에 담지 않는다.
        yield _frame(ChatStreamDone(request=result))
    except DatabaseUnavailableError:
        yield _frame(
            ChatStreamError(
                status_code=503,
                request_reserved=reserved,
                message="대화 저장 상태를 확인하지 못했습니다. 같은 요청의 상태를 조회해 주세요.",
            )
        )
    except HTTPException as exc:
        # 스트림 시작 뒤에는 HTTP 상태를 바꿀 수 없으므로 안전한 오류 이벤트를 보낸다.
        code = exc.status_code if exc.status_code in {404, 409, 503} else 500
        message = (
            exc.detail if isinstance(exc.detail, str) else "요청 상태를 확인해 주세요."
        )
        yield _frame(
            ChatStreamError(
                status_code=code, message=message, request_reserved=reserved
            )
        )
    except Exception:
        yield _frame(
            ChatStreamError(
                status_code=500,
                request_reserved=reserved,
                message="대화 전송이 중단됐습니다. 같은 요청의 상태를 조회해 주세요.",
            )
        )
    finally:
        connected = False
        # task.cancel()은 실행 중인 스레드를 중단하지 못한다. 중복 실행 없이 저장을 마친다.
