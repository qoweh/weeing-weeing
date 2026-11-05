"""인증된 챗봇 HTTP 입구 (#91). FAQ 버튼 선택과 자유 질문 경로를 분리한다.

동기 라우트는 FastAPI 작업 스레드에서 실행된다. 사용자 사번은 Bearer 세션에서만
얻고 대화 소유권은 DB가 매번 확인한다. 개인 기록은 공유 검색 색인에 넣지 않는다.
"""

from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator

from weeing_weeing.agent.interface import (
    FaqCatalog,
    FaqCatalogError,
    FaqNotFoundError,
    get_chat_service,
    load_faq_catalog,
    trace_user,
)
from weeing_weeing.api.auth import CurrentUser
from weeing_weeing.api.chat_storage import StoredChatService
from weeing_weeing.api.chat_stream import stream_chat
from weeing_weeing.contracts import (
    ChatConversation,
    ChatConversationPage,
    ChatQuestion,
    ChatRequestView,
    ChatSearchConditions,
    ChatSubmission,
    FaqQuestion,
    FaqSelection,
    FaqTopic,
)
from weeing_weeing.contracts.chat import ChatModel
from weeing_weeing.db import interface as db


def _private(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(_private)])


def _call(operation, *args, **kwargs):
    """예외 원문을 반환하지 않고, 프론트엔드가 처리할 안전한 HTTP 오류로 변환한다."""
    try:
        return operation(*args, **kwargs)
    except (db.ChatNotFoundError, FaqNotFoundError) as exc:
        raise HTTPException(
            status_code=404, detail="요청한 항목을 찾을 수 없습니다."
        ) from exc
    except db.ChatConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FaqCatalogError as exc:
        raise HTTPException(
            status_code=503, detail="FAQ 목록을 불러오지 못했습니다."
        ) from exc


def chats() -> db.SqlChats:
    return db.get_chats()


@lru_cache(maxsize=1)
def _faq_snapshot() -> FaqCatalog:
    # 목록과 선택 응답이 같은 검토본을 쓰도록 프로세스 수명 동안 재사용한다.
    return load_faq_catalog()


def faq_catalog() -> FaqCatalog:
    return _call(_faq_snapshot)


Chats = Annotated[db.SqlChats, Depends(chats)]
Catalog = Annotated[FaqCatalog, Depends(faq_catalog)]


def stored_chat(repo: Chats) -> StoredChatService:
    def new_service():
        from weeing_weeing.api.chat_knowledge import get_chat_knowledge

        catalog = _faq_snapshot()
        return get_chat_service(get_chat_knowledge(), faq=catalog)

    # 저장된 중복 요청은 카탈로그·검색·LLM 장애와 무관하게 반환한다.
    # 새 실행 토큰을 얻은 요청만 FAQ 스냅샷 또는 생성 서비스를 연다.
    return StoredChatService(
        repo, faq_factory=_faq_snapshot, service_factory=new_service
    )


Stored = Annotated[StoredChatService, Depends(stored_chat)]


class ConversationCreate(ChatModel):
    title: str = Field(default="새 대화", min_length=1, max_length=100)
    conditions: ChatSearchConditions = Field(default_factory=ChatSearchConditions)


class ConversationUpdate(ChatModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    conditions: ChatSearchConditions | None = None
    mode: Literal["FAQ", "CHAT"] | None = None

    @field_validator("title", "conditions", "mode", mode="before")
    @classmethod
    def _not_null(cls, value):
        if value is None:
            raise ValueError(
                "변경할 값은 null일 수 없습니다. 유지할 항목은 생략하세요."
            )
        return value


def _request_result(result: ChatRequestView, response: Response) -> ChatRequestView:
    """항상 같은 JSON 계약을 반환하고, 처리 중인 요청만 폴링 주소와 202를 제공한다."""
    response.headers["Location"] = (
        f"/chat/conversations/{result.conversation_id}/requests/{result.submission.request_id}"
    )
    if result.state in {"RESERVED", "RUNNING"}:
        response.status_code = 202
        response.headers["Retry-After"] = "1"
    elif result.state == "UNKNOWN":
        response.status_code = 409
    elif result.error_code == "FAQ_NOT_FOUND":
        response.status_code = 404
    elif result.state == "FAILED":
        response.status_code = 503
    else:
        # COMPLETED는 '응답 저장 완료'다. response.status가 OK인지 화면에서 별도로 확인한다.
        response.status_code = 200
    return result


_REQUEST_RESPONSES = {
    202: {
        "model": ChatRequestView,
        "description": "처리 중. Location 주소로 상태 조회",
    },
    404: {"description": "없는 항목·타인 대화·조회할 수 없는 FAQ"},
    409: {"description": "본문/모드 충돌 또는 결과 불명"},
    503: {"description": "실행 전 준비 실패 또는 DB 장애"},
}


@router.get("/faq/topics")
def faq_topics(user: CurrentUser, catalog: Catalog) -> list[FaqTopic]:
    return _call(catalog.list_topics)


@router.get("/faq/topics/{topic_id}/questions")
def faq_questions(
    topic_id: str, user: CurrentUser, catalog: Catalog
) -> list[FaqQuestion]:
    return _call(catalog.list_questions, topic_id)


@router.post("/conversations", status_code=201)
def create_conversation(
    body: ConversationCreate, user: CurrentUser, repo: Chats
) -> ChatConversation:
    return _call(repo.create_conversation, user.employee_no, **body.model_dump())


@router.get("/conversations")
def list_conversations(
    user: CurrentUser,
    repo: Chats,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ChatConversation]:
    return _call(repo.list_conversations, user.employee_no, limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: UUID,
    user: CurrentUser,
    repo: Chats,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> ChatConversationPage:
    return _call(
        repo.get_conversation,
        user.employee_no,
        conversation_id,
        after_sequence=after_sequence,
        limit=limit,
    )


@router.patch("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: UUID, body: ConversationUpdate, user: CurrentUser, repo: Chats
) -> ChatConversation:
    return _call(
        repo.update_conversation,
        user.employee_no,
        conversation_id,
        **body.model_dump(exclude_unset=True),
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID, user: CurrentUser, repo: Chats
) -> Response:
    _call(repo.delete_conversation, user.employee_no, conversation_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post(
    "/conversations/{conversation_id}/faq-selections", responses=_REQUEST_RESPONSES
)
def select_faq(
    conversation_id: UUID,
    body: FaqSelection,
    user: CurrentUser,
    service: Stored,
    response: Response,
    retry: bool = False,
) -> ChatRequestView:
    submission = ChatSubmission(kind="FAQ", **body.model_dump())
    return _request_result(
        _call(
            service.submit, user.employee_no, conversation_id, submission, retry=retry
        ),
        response,
    )


@router.post("/conversations/{conversation_id}/messages", responses=_REQUEST_RESPONSES)
def send_message(
    conversation_id: UUID,
    body: ChatQuestion,
    user: CurrentUser,
    service: Stored,
    response: Response,
    retry: bool = False,
) -> ChatRequestView:
    # 생략한 검색 조건은 대화에서 선택한 조건을 사용한다. 기본 {}로 덮어쓰지 않는다.
    submission = ChatSubmission(
        kind="CHAT",
        request_id=body.request_id,
        question=body.question,
        conditions=body.conditions if "conditions" in body.model_fields_set else None,
    )
    # 서버 하나를 여럿이 써도 사용량 기록이 로그인한 사람으로 남게 한다.
    with trace_user(user.name):
        result = _call(
            service.submit, user.employee_no, conversation_id, submission, retry=retry
        )
    return _request_result(result, response)


@router.post(
    "/conversations/{conversation_id}/messages/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "진행 상태와 검증·저장 후 답변 전송",
        }
    },
)
def stream_message(
    conversation_id: UUID,
    body: ChatQuestion,
    user: CurrentUser,
    service: Stored,
    repo: Chats,
    retry: bool = False,
):
    # 인증·소유권은 헤더 전송 전에도 검사한다. 예약·실행 때 DB가 다시 검사한다.
    _call(repo.get_conversation, user.employee_no, conversation_id, limit=1)
    submission = ChatSubmission(
        kind="CHAT",
        request_id=body.request_id,
        question=body.question,
        conditions=body.conditions if "conditions" in body.model_fields_set else None,
    )

    def execute(progress):
        # 실행은 다른 스레드에서 돌므로 문맥 변수를 그 안에서 건다.
        with trace_user(user.name):
            return _call(
                service.submit,
                user.employee_no,
                conversation_id,
                submission,
                retry=retry,
                on_progress=progress,
            )

    return StreamingResponse(
        stream_chat(body.request_id, execute),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/conversations/{conversation_id}/requests/{request_id}",
    responses=_REQUEST_RESPONSES,
)
def get_request(
    conversation_id: UUID,
    request_id: UUID,
    user: CurrentUser,
    repo: Chats,
    response: Response,
) -> ChatRequestView:
    return _request_result(
        _call(repo.get_request, user.employee_no, conversation_id, request_id), response
    )
