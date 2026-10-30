"""#90: 소유자 전용 대화와 요청 ID 기반 실행 예약. 외부 호출 중 DB 잠금을 유지하지 않는다."""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text

from weeing_weeing.contracts import (
    ChatContext,
    ChatResponse,
    ChatSearchConditions,
    ChatTurn,
)
from weeing_weeing.contracts.chat_storage import (
    ChatConversation,
    ChatConversationPage,
    ChatRequestView,
    ChatSavedMessage,
    ChatSubmission,
)
from weeing_weeing.db.models import (
    ChatConversationRow,
    ChatMessageRow,
    ChatRequestRow,
    UserRow,
)
from weeing_weeing.db.session import Repository, now, utc


class ChatNotFoundError(LookupError):
    """없는 대화·타인 대화·비활성 사용자 모두 같은 오류로 숨긴다."""


class ChatConflictError(ValueError):
    """요청 ID 본문 충돌, 현재 처리 중, 모드/조건 변경 또는 만료된 실행 토큰."""


@dataclass(frozen=True)
class ChatClaim:
    request: ChatRequestView
    execution_token: UUID | None = field(default=None, repr=False)


def _active(session, actor_id):
    user = session.get(UserRow, actor_id)
    if user is None or not user.is_active:
        raise ChatNotFoundError("대화를 찾을 수 없습니다.")


def _owned(session, actor_id, conversation_id, *, lock=False):
    _active(session, actor_id)
    query = select(ChatConversationRow).where(
        ChatConversationRow.conversation_id == str(conversation_id),
        ChatConversationRow.owner_id == actor_id,
    )
    if lock:
        query = query.with_for_update()
    row = session.scalar(query)
    if row is None:
        raise ChatNotFoundError("대화를 찾을 수 없습니다.")
    return row


def _conversation(row):
    return ChatConversation(
        conversation_id=row.conversation_id,
        title=row.title,
        conditions=row.conditions,
        mode=row.mode,
        created_at=utc(row.created_at),
        updated_at=utc(row.updated_at),
    )


def _request(session, conversation_id, request_id):
    row = session.get(ChatRequestRow, (str(conversation_id), str(request_id)))
    if row is None:
        raise ChatNotFoundError("요청을 찾을 수 없습니다.")
    return row


def _saved_submission(payload):
    # 이전 DB 기록만 호환한다. 새 HTTP 요청은 삭제한 필드를 계속 거부한다.
    return ChatSubmission.model_validate(
        {k: v for k, v in payload.items() if k != "faq_version"}
    )


def _saved_response(payload):
    if payload is None:
        return None
    # 기존 JSON을 변경하지 않고, 과거 FAQ 출처의 폐지된 필드만 읽기 시 제외한다.
    sources = [
        (
            {k: v for k, v in source.items() if k != "faq_version"}
            if source.get("kind") == "FAQ"
            else source
        )
        for source in payload.get("sources", [])
    ]
    return ChatResponse.model_validate(payload | {"sources": sources})


def _view(row):
    return ChatRequestView(
        conversation_id=row.conversation_id,
        submission=_saved_submission(row.submission),
        state=row.state,
        conditions=row.conditions,
        response=_saved_response(row.response),
        retry_allowed=row.retry_allowed,
        error_code="PREPARATION_FAILED"
        if row.error_code == "FAQ_VERSION_CONFLICT"
        else row.error_code,
        created_at=utc(row.created_at),
        updated_at=utc(row.updated_at),
    )


def _fingerprint(submission):
    # 이전 대화의 현재 상태가 아닌, 클라이언트가 보낸 정규화된 본문만 비교한다.
    payload = submission.model_dump(mode="json", exclude={"request_id"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _expire(session, conversation):
    if not conversation.active_request_id:
        return
    row = _request(
        session, conversation.conversation_id, conversation.active_request_id
    )
    if row.state in {"RESERVED", "RUNNING"} and utc(row.lease_until) <= now():
        before_start = row.state == "RESERVED"
        row.state = "FAILED" if before_start else "UNKNOWN"
        row.retry_allowed = before_start
        row.error_code = "EXPIRED_BEFORE_START" if before_start else "RESULT_UNKNOWN"
        row.execution_token = (
            None  # 늦게 돌아온 이전 작업자는 새 결과를 덮어쓸 수 없다.
        )
        row.updated_at = now()
        conversation.active_request_id = None
        conversation.updated_at = now()


def _token(row, execution_token, states):
    if row.execution_token != str(execution_token) or row.state not in states:
        raise ChatConflictError("이미 처리됐거나 실행 소유권이 만료된 요청입니다.")


class SqlChats(Repository):
    def __init__(self, engine, *, lease_seconds=900):
        super().__init__(engine)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("실행 예약 기간은 1~3600초")
        self.lease_seconds = lease_seconds

    @contextmanager
    def _write(self):
        with self._transaction() as session:
            # SQLite에는 행 잠금이 없어 먼저 쓰기 잠금을 잡는다. PostgreSQL은 대화 행만 잠근다.
            if self._engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            yield session

    def create_conversation(
        self, actor_id, *, title="새 대화", conditions=None, mode="FAQ"
    ):
        """생성자는 인증 계층이 전달한 actor_id로 고정한다. 본문에 owner_id를 받지 않는다."""
        stamp = now()
        value = ChatConversation(
            conversation_id=uuid4(),
            title=title,
            conditions=conditions or ChatSearchConditions(),
            mode=mode,
            created_at=stamp,
            updated_at=stamp,
        )
        with self._write() as session:
            _active(session, actor_id)
            session.add(
                ChatConversationRow(
                    conversation_id=str(value.conversation_id),
                    owner_id=actor_id,
                    title=value.title,
                    conditions=value.conditions.model_dump(mode="json"),
                    mode=value.mode,
                    next_sequence=1,
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
        return value

    def list_conversations(self, actor_id, *, limit=50, offset=0):
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or offset < 0
        ):
            raise ValueError("대화 목록 범위 오류")
        with self._transaction() as session:
            _active(session, actor_id)
            rows = session.scalars(
                select(ChatConversationRow)
                .where(ChatConversationRow.owner_id == actor_id)
                .order_by(
                    ChatConversationRow.updated_at.desc(),
                    ChatConversationRow.conversation_id,
                )
                .offset(offset)
                .limit(limit)
            )
            return [_conversation(row) for row in rows]

    def get_conversation(
        self, actor_id, conversation_id, *, after_sequence=0, limit=100
    ):
        """소유자 확인 후 메시지를 순서대로 반환한다. 만료 요청은 자동 재실행하지 않는다."""
        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            raise ValueError("메시지 목록 범위 오류")
        with self._write() as session:
            conversation = _owned(session, actor_id, conversation_id, lock=True)
            _expire(session, conversation)
            messages = session.scalars(
                select(ChatMessageRow)
                .where(
                    ChatMessageRow.conversation_id == str(conversation_id),
                    ChatMessageRow.sequence > after_sequence,
                )
                .order_by(ChatMessageRow.sequence)
                .limit(limit + 1)
            ).all()
            values = []
            for message in messages[:limit]:
                request = _request(session, conversation_id, message.request_id)
                values.append(
                    ChatSavedMessage(
                        sequence=message.sequence,
                        request_id=message.request_id,
                        kind=request.submission["kind"],
                        role=message.role,
                        content=message.content,
                        state=request.state,
                        response=_saved_response(request.response)
                        if message.role == "assistant"
                        else None,
                        created_at=utc(message.created_at),
                    )
                )
            return ChatConversationPage(
                conversation=_conversation(conversation),
                messages=values,
                has_more=len(messages) > limit,
            )

    def update_conversation(
        self, actor_id, conversation_id, *, title=None, conditions=None, mode=None
    ):
        """선택 조건·모드는 소유자만 바꾼다. 처리 중에는 문맥을 바꾸지 않는다."""
        with self._write() as session:
            row = _owned(session, actor_id, conversation_id, lock=True)
            _expire(session, row)
            if row.active_request_id:
                raise ChatConflictError("처리 중인 요청이 있습니다.")
            changes = {
                k: v
                for k, v in dict(title=title, conditions=conditions, mode=mode).items()
                if v is not None
            }
            value = ChatConversation.model_validate(
                _conversation(row).model_dump() | changes
            )
            row.title, row.mode = value.title, value.mode
            row.conditions = value.conditions.model_dump(mode="json")
            row.updated_at = now()
            return _conversation(row)

    def delete_conversation(self, actor_id, conversation_id):
        """소유자의 명시 삭제는 메시지·요청까지 cascade한다. 기존 보고서는 지우지 않는다."""
        with self._write() as session:
            row = _owned(session, actor_id, conversation_id, lock=True)
            session.delete(row)

    def reserve_request(self, actor_id, conversation_id, submission, *, retry=False):
        """동일 ID에는 하나의 실행 토큰만 발급한다. 중복 호출자는 토큰 없이 저장 상태를 받는다."""
        submission = ChatSubmission.model_validate(submission)
        with self._write() as session:
            conversation = _owned(session, actor_id, conversation_id, lock=True)
            _expire(session, conversation)
            row = session.get(
                ChatRequestRow, (str(conversation_id), str(submission.request_id))
            )
            if row is not None:
                if _fingerprint(_saved_submission(row.submission)) != _fingerprint(
                    submission
                ):
                    raise ChatConflictError(
                        "같은 요청 ID에 다른 내용을 보낼 수 없습니다."
                    )
                if not retry or row.state != "FAILED" or not row.retry_allowed:
                    return ChatClaim(_view(row))
            if conversation.active_request_id:
                raise ChatConflictError("대화의 이전 요청이 처리 중입니다.")
            if submission.kind == "CHAT" and conversation.mode != "CHAT":
                raise ChatConflictError("채팅 시작으로 전환한 뒤 자유 질문을 보내세요.")
            if row is None:
                selected = ChatSearchConditions.model_validate(conversation.conditions)
                if (
                    submission.conditions is not None
                    and submission.conditions != selected
                ):
                    raise ChatConflictError("대화의 선택 조건을 먼저 갱신하세요.")
                row = ChatRequestRow(
                    conversation_id=str(conversation_id),
                    request_id=str(submission.request_id),
                    fingerprint=_fingerprint(submission),
                    submission=submission.model_dump(mode="json"),
                    conditions=selected.model_dump(mode="json"),
                    user_sequence=conversation.next_sequence,
                    created_at=now(),
                    updated_at=now(),
                    retry_allowed=False,
                    state="RESERVED",
                )
                session.add(row)
                session.flush()
                content = (
                    submission.question
                    if submission.kind == "CHAT"
                    else f"FAQ 선택: {submission.faq_id}"
                )
                session.add(
                    ChatMessageRow(
                        conversation_id=str(conversation_id),
                        request_id=str(submission.request_id),
                        sequence=row.user_sequence,
                        role="user",
                        content=content,
                        created_at=now(),
                    )
                )
                conversation.next_sequence += 2
            token = uuid4()
            row.state, row.execution_token = "RESERVED", str(token)
            row.lease_until = now() + timedelta(seconds=self.lease_seconds)
            row.retry_allowed, row.error_code, row.updated_at = False, None, now()
            conversation.active_request_id = str(submission.request_id)
            conversation.updated_at = now()
            session.flush()
            return ChatClaim(_view(row), token)

    def start_request(self, actor_id, conversation_id, request_id, execution_token):
        """외부 실행 직전에 RUNNING을 커밋한다. 이 뒤 불명확한 실패는 같은 ID로 재실행하지 않는다."""
        with self._write() as session:
            conversation = _owned(session, actor_id, conversation_id, lock=True)
            _expire(session, conversation)
            row = _request(session, conversation_id, request_id)
            _token(row, execution_token, {"RESERVED"})
            row.state, row.updated_at = "RUNNING", now()
            return _view(row)

    def get_request(self, actor_id, conversation_id, request_id):
        with self._write() as session:
            conversation = _owned(session, actor_id, conversation_id, lock=True)
            _expire(session, conversation)
            return _view(_request(session, conversation_id, request_id))

    def fail_request(
        self,
        actor_id,
        conversation_id,
        request_id,
        execution_token,
        *,
        code="PREPARATION_FAILED",
    ):
        """실행 전 실패만 재시도 허용. 실행 이후 결과 불명은 UNKNOWN으로 고정한다."""
        if code not in {"PREPARATION_FAILED", "FAQ_NOT_FOUND"}:
            raise ValueError("알 수 없는 실행 전 실패 코드")
        with self._write() as session:
            conversation = _owned(session, actor_id, conversation_id, lock=True)
            row = _request(session, conversation_id, request_id)
            _token(row, execution_token, {"RESERVED", "RUNNING"})
            before_start = row.state == "RESERVED"
            row.state = "FAILED" if before_start else "UNKNOWN"
            row.retry_allowed = before_start and code == "PREPARATION_FAILED"
            row.error_code = code if before_start else "RESULT_UNKNOWN"
            row.execution_token, row.updated_at = None, now()
            conversation.active_request_id, conversation.updated_at = None, now()
            return _view(row)

    def complete_request(
        self,
        actor_id,
        conversation_id,
        request_id,
        execution_token,
        response,
        *,
        question_text=None,
    ):
        """질문 스냅샷·응답·메시지 한 쌍을 한 트랜잭션으로 저장한다."""
        response = ChatResponse.model_validate(response)
        if response.request_id != UUID(str(request_id)):
            raise ChatConflictError("응답 요청 ID가 다릅니다.")
        with self._write() as session:
            conversation = _owned(session, actor_id, conversation_id, lock=True)
            _expire(session, conversation)
            row = _request(session, conversation_id, request_id)
            _token(row, execution_token, {"RUNNING", "COMPLETED"})
            saved_response = response.model_dump(mode="json")
            if row.state == "COMPLETED":
                if _saved_response(row.response) != response:
                    raise ChatConflictError("저장된 응답은 바꿀 수 없습니다.")
                return _view(row)
            submission = _saved_submission(row.submission)
            user_message = session.get(
                ChatMessageRow, (str(conversation_id), row.user_sequence)
            )
            if submission.kind == "FAQ":
                if (
                    response.intent != "FAQ"
                    or response.status != "OK"
                    or any(
                        source.kind != "FAQ" or source.faq_id != submission.faq_id
                        for source in response.sources
                    )
                ):
                    raise ChatConflictError("선택한 FAQ와 응답 ID가 다릅니다.")
                if (
                    not question_text
                    or not question_text.strip()
                    or len(question_text.strip()) > 2000
                ):
                    raise ValueError("FAQ 대표 질문 스냅샷 필요")
                user_message.content = question_text.strip()
            elif question_text is not None and question_text != submission.question:
                raise ChatConflictError("원래 질문을 바꿀 수 없습니다.")
            content = "\n".join(
                [response.message]
                + [p.text for p in response.parts]
                + response.clarification_questions
            )
            session.add(
                ChatMessageRow(
                    conversation_id=str(conversation_id),
                    request_id=str(request_id),
                    sequence=row.user_sequence + 1,
                    role="assistant",
                    content=content,
                    created_at=now(),
                )
            )
            row.state, row.response = "COMPLETED", saved_response
            row.retry_allowed, row.error_code, row.updated_at = False, None, now()
            conversation.active_request_id, conversation.updated_at = None, now()
            session.flush()
            return _view(row)

    def get_context(self, actor_id, conversation_id):
        """완료된 최근 질문·답변만 모델 문맥으로 만든다. 미완료/실패·도구 프롬프트는 제외한다."""
        with self._transaction() as session:
            _owned(session, actor_id, conversation_id)
            pairs = session.execute(
                select(ChatRequestRow, ChatMessageRow)
                .join(
                    ChatMessageRow,
                    (ChatRequestRow.conversation_id == ChatMessageRow.conversation_id)
                    & (ChatRequestRow.request_id == ChatMessageRow.request_id)
                    & (ChatMessageRow.role == "user"),
                )
                .where(
                    ChatRequestRow.conversation_id == str(conversation_id),
                    ChatRequestRow.state == "COMPLETED",
                )
                .order_by(ChatRequestRow.user_sequence.desc())
                .limit(10)
            ).all()
            turns = []
            for request, message in reversed(pairs):
                response = _saved_response(request.response)
                if response.status == "FAILED":
                    continue
                answer = "\n".join(
                    [response.message]
                    + [p.text for p in response.parts]
                    + response.clarification_questions
                )
                turns.extend(
                    [
                        ChatTurn(role="user", content=message.content[:4000]),
                        ChatTurn(role="assistant", content=answer[:4000]),
                    ]
                )
            while sum(len(turn.content) for turn in turns) > 16000:
                turns = turns[2:]
            return ChatContext(recent_turns=turns)
