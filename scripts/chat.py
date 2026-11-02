"""Claude·공유 RAG·DB 챗봇 실행. 키는 --ask-key로 숨김 입력할 수 있다 (#89)."""

import argparse
import getpass
import sys
from uuid import uuid4

from pydantic import ValidationError

from weeing_weeing.agent.interface import get_llm_client
from weeing_weeing.api.chat_knowledge import build_chat_service
from weeing_weeing.config import get_settings
from weeing_weeing.contracts import (
    ChatContext,
    ChatQuestion,
    ChatSearchConditions,
    ChatTurn,
)
from weeing_weeing.rag.interface import close_rag_resources

FAILURE_HELP = {
    "LLM_AUTHENTICATION": "Claude 키·모델 사용 권한을 확인하세요.",
    "RATE_LIMITED": "호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.",
    "LLM_SERVICE": "Claude 연결·모델 설정 또는 일시 장애를 확인하세요.",
    "SEARCH_UNAVAILABLE": "DB·문서 등록·색인·검색 모델을 확인하세요.",
    "TIMEOUT": "전체 처리 시간 예산을 초과했습니다.",
    "INVALID_RESPONSE": "답변·근거 검토 결과를 검증하지 못했습니다.",
}


def remember(context, question, response):
    """최근 대화만 메모리에 보관한다. 디스크 저장 없이 계약의 길이 상한을 지킨다."""
    if response.status == "FAILED":
        return context
    text = "\n".join(
        [response.message]
        + [part.text for part in response.parts]
        + response.clarification_questions
    )
    turns = context.recent_turns + [
        ChatTurn(role="user", content=question.question),
        ChatTurn(role="assistant", content=text[:4000]),
    ]
    while len(turns) > 20 or sum(len(turn.content) for turn in turns) > 16000:
        turns = turns[2:]
    return ChatContext(recent_turns=turns)


def show(response):
    """사용자가 읽을 답변과 실제 서버 출처를 표시한다. SDK 원문 오류는 출력하지 않는다."""
    print(f"\n챗봇 [{response.status}]: {response.message}")
    for part in response.parts:
        print(f"\n{part.text}")
    for question in response.clarification_questions:
        print(f"확인 질문: {question}")
    displayed_sources = set()
    for source in response.sources:
        if source.kind == "DOCUMENT":
            detail = (
                f"{source.doc_id} v{source.doc_version}, 페이지 {source.page}"
                if source.page
                else f"{source.doc_id} v{source.doc_version}, {source.section}"
            )
            display_key = (
                source.kind,
                source.doc_id,
                source.doc_version,
                source.page,
                source.section if source.page is None else None,
            )
        elif source.kind == "REPORT":
            detail = f"{source.report_id} v{source.report_version}"
            display_key = (
                source.kind,
                source.report_id,
                source.report_version,
                source.synthetic,
            )
        elif source.kind == "HISTORY_QUERY":
            detail = f"DB 승인 보고서 {source.total}건"
            display_key = (source.kind, source.source_id)
        else:
            detail = f"FAQ {source.faq_id}"
            display_key = (source.kind, source.faq_id)
        if display_key in displayed_sources:
            continue
        displayed_sources.add(display_key)
        print(f"출처: {source.title} — {detail}")
    if response.failure:
        print(
            FAILURE_HELP.get(response.failure.code, "처리 중 오류가 발생했습니다.")
            + f" [{response.failure.code}]"
        )


def show_usage(service, request_id, *, stream):
    usage = getattr(service, "last_run", None)
    if usage is None or usage.request_id != str(request_id):
        return
    total = usage.total
    tokens = (
        f"입력 {total.input_tokens} / 출력 {total.output_tokens} 토큰"
        if total is not None
        else f"토큰 합계 미확인 (사용량 누락/재시도 불확실 {usage.unknown_calls}회)"
    )
    print(
        f"호출 {len(usage.calls)}회(근거 검토 포함, 통신 시도 {sum(c.attempts for c in usage.calls)}회), {tokens}, {usage.elapsed_s:.1f}초",
        file=stream,
    )
    if usage.tool_names:
        print("도구: " + " → ".join(usage.tool_names), file=stream)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", help="생략하면 대화 모드")
    parser.add_argument(
        "--interactive", action="store_true", help="이전 대화를 이어서 질문"
    )
    parser.add_argument(
        "--ask-key",
        action="store_true",
        help="현재 터미널에서 키 숨김 입력, 파일 저장 없음",
    )
    parser.add_argument(
        "--stats", action="store_true", help="호출·토큰·시간·도구 목록을 stderr로 출력"
    )
    parser.add_argument("--asset-id")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    args = parser.parse_args(argv)
    if args.interactive and args.question:
        parser.error("대화 모드에서는 질문 인자를 생략하세요.")
    interactive = args.interactive or args.question is None
    client = None
    try:
        conditions = ChatSearchConditions(
            asset_id=args.asset_id, date_from=args.date_from, date_to=args.date_to
        )
        api_key = None
        if args.ask_key:
            # 키를 argv·환경변수·파일에 넣지 않는다. 비TTY의 getpass 에코 대체 동작도 막는다.
            if not sys.stdin.isatty():
                parser.error("--ask-key는 사용자가 직접 연 일반 터미널에서 실행하세요.")
            api_key = getpass.getpass(
                "Claude API 키 (화면 표시·파일 저장 없음): "
            ).strip()
            if not api_key:
                print("API 키가 입력되지 않았습니다.", file=sys.stderr)
                return 2
        client = get_llm_client(entrypoint="chatbot-cli", api_key=api_key)
        api_key = None
        service = build_chat_service(client=client)
        context = ChatContext()
        if interactive:
            print(
                "Claude 대화: 실제 API 비용 발생. /exit 종료, /reset 대화 초기화. 대화는 파일에 저장하지 않습니다."
            )
        while True:
            if interactive:
                try:
                    text = input("\n나: ").strip()
                except EOFError:
                    return 0
                if text in {"/exit", "/quit"}:
                    return 0
                if text == "/reset":
                    context = ChatContext()
                    print("대화 문맥을 초기화했습니다.")
                    continue
                if not text:
                    continue
                if text.startswith("/"):
                    print("명령: /exit, /reset")
                    continue
            else:
                text = args.question
            try:
                question = ChatQuestion(
                    request_id=uuid4(), question=text, conditions=conditions
                )
            except ValidationError:
                print("질문은 공백이 아닌 1~2000자로 입력하세요.", file=sys.stderr)
                if interactive:
                    continue
                return 2
            result = service.reply(
                question, context=context, timeout_s=get_settings().llm_timeout_s
            )
            if interactive:
                show(result)
                if args.stats:
                    show_usage(service, question.request_id, stream=sys.stderr)
                context = remember(context, question, result)
            else:
                print(result.model_dump_json(indent=2))
                if args.stats:
                    show_usage(service, question.request_id, stream=sys.stderr)
                return 1 if result.status == "FAILED" else 0
    except KeyboardInterrupt:
        print("\n대화를 종료했습니다.")
        return 130
    except Exception as exc:
        print(f"챗봇 시작/실행 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    finally:
        # 키를 담은 SDK와 검색 저장소를 명시적으로 닫는다. 비밀값을 출력하지 않는다.
        close = getattr(client, "close", None) if client is not None else None
        for cleanup in (close, close_rag_resources):
            if cleanup:
                try:
                    cleanup()
                except Exception as exc:
                    print(f"종료 정리 실패: {type(exc).__name__}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
