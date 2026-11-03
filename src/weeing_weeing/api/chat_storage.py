"""인증한 사용자 → 중복 예약 → FAQ/Claude → 응답 저장을 연결한다 (#90).

HTTP(#91)는 세션의 사번을 actor_id로 전달한다. 요청 본문의 사용자 ID는 받지 않는다.
대화 조회·수정·삭제는 db.interface의 대화 저장소가 소유권을 검사해 수행한다.
"""

import math
from collections.abc import Callable
from uuid import UUID

from weeing_weeing.agent.interface import (
    ChatService,
    FaqCatalog,
    FaqNotFoundError,
    load_faq_catalog,
)
from weeing_weeing.contracts import (
    ChatQuestion,
    ChatRequestView,
    ChatResponse,
    ChatSubmission,
    FaqSelection,
)
from weeing_weeing.contracts.chat_stream import ChatProgress
from weeing_weeing.db.interface import SqlChats


def _default_service():
    from weeing_weeing.api.chat_knowledge import build_chat_service

    return build_chat_service()


class StoredChatService:
    """실행마다 전용 ChatService를 생성한다. 프로세스 간 중복 방지는 DB 예약이 담당한다.

    주입하는 service_factory도 요청마다 독립된 서비스를 반환해야 한다.
    과거 기록 조회에는 검색기나 Claude가 필요하지 않다.
    """

    def __init__(
        self,
        repository: SqlChats,
        *,
        faq: FaqCatalog | None = None,
        faq_factory: Callable[[], FaqCatalog] = load_faq_catalog,
        service_factory: Callable[[], ChatService] = _default_service,
    ):
        self.repository = repository
        self._faq = faq
        self._faq_factory = faq_factory
        self._service_factory = service_factory

    def submit(
        self,
        actor_id: str,
        conversation_id: UUID,
        submission: ChatSubmission,
        *,
        retry: bool = False,
        timeout_s: float = 120,
        on_progress: ChatProgress | None = None,
    ) -> ChatRequestView:
        """동일 요청은 저장 상태만 반환한다. 실행 전 실패에만 명시적 재시도를 허용한다."""
        if (
            isinstance(timeout_s, bool)
            or not math.isfinite(timeout_s)
            or not 0 < timeout_s <= 600
        ):
            raise ValueError("대화 실행 예산은 0초 초과 600초 이하")
        # 같은 요청 ID를 DB에서 발견하면, 저장된 응답을 담아서 실행 토큰 없이 반환
        claim = self.repository.reserve_request(
            actor_id, conversation_id, submission, retry=retry
        )
        request = claim.request
        if on_progress:
            on_progress("accepted")

        # 실행 토큰이 없으면 예약만 하고 반환한다. 이미 실행된 요청은 재실행하지 않는다. (답변은 request.response에 담겨 있다)
        if claim.execution_token is None:
            return request

        token = claim.execution_token
        request_id = request.submission.request_id
        question_text = None
        try:
            if request.submission.kind == "FAQ":
                # 서버에 보관한 대표 질문·답변을 저장한다. FAQ 오류를 LLM 호출로 우회하지 않는다.
                catalog = self._faq if self._faq is not None else self._faq_factory()
                selection = FaqSelection(
                    request_id=request_id,
                    faq_id=request.submission.faq_id,
                )
                response = catalog.answer(selection, conditions=request.conditions)
                question_text = catalog.get_answer(selection.faq_id).question.question
                self.repository.start_request(
                    actor_id, conversation_id, request_id, token
                )
            else:
                service = self._service_factory()
                context = self.repository.get_context(actor_id, conversation_id)
                question = ChatQuestion(
                    request_id=request_id,
                    question=request.submission.question,
                    conditions=request.conditions,
                )
                # 외부 호출 직전에 시작 상태를 커밋한다. DB 잠금은 호출 동안 유지하지 않는다.
                self.repository.start_request(
                    actor_id, conversation_id, request_id, token
                )
                progressive = getattr(service, "reply_with_progress", None)
                if on_progress is not None and callable(progressive):
                    answer = progressive(
                        question,
                        context=context,
                        timeout_s=timeout_s,
                        on_progress=on_progress,
                    )
                else:
                    if on_progress:
                        on_progress("generating")
                    answer = service.reply(
                        question, context=context, timeout_s=timeout_s
                    )
                response = ChatResponse.model_validate(answer)
        except FaqNotFoundError:
            return self.repository.fail_request(
                actor_id, conversation_id, request_id, token, code="FAQ_NOT_FOUND"
            )
        except Exception:
            # 예외 원문은 저장/로그에 남기지 않는다. DB가 실행 전/후를 구분해 재시도를 판단한다.
            return self.repository.fail_request(
                actor_id, conversation_id, request_id, token
            )
        # 생성 후 저장 실패는 호출자에게 알린다. 실행 전 실패로 바꾸면 중복 과금 위험이 있다.
        if on_progress:
            on_progress("saving")
        return self.repository.complete_request(
            actor_id,
            conversation_id,
            request_id,
            token,
            response,
            question_text=question_text,
        )
