"""Claude 호출 없이 FAQ·RAG 검색·DB 기간 조회를 각각 실행한다."""

import argparse
import json
from uuid import uuid4

from weeing_weeing.agent.interface import load_faq_catalog
from weeing_weeing.api.chat_knowledge import get_chat_knowledge
from weeing_weeing.contracts import ChatSearchConditions, FaqSelection
from weeing_weeing.contracts.chat_tools import ChatHistoryQuery, ChatSearchQuery
from weeing_weeing.rag.interface import close_rag_resources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    faq = commands.add_parser("faq", help="FAQ 주제·질문 목록 또는 ID 선택 답변")
    faq.add_argument("--faq-id")
    search = commands.add_parser("search", help="검색어·조건을 직접 지정한 RAG 검색")
    search.add_argument("query")
    search.add_argument(
        "--kind", choices=["MANUAL", "MAINTENANCE_HISTORY"], default="MANUAL"
    )
    history = commands.add_parser(
        "history", help="최신 승인 보고서의 정확한 목록·건수 조회"
    )
    for command in (search, history):
        command.add_argument("--asset-id")
        command.add_argument("--code")
        command.add_argument("--date-from")
        command.add_argument("--date-to")
        command.add_argument("--limit", type=int, default=5)
        command.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args(argv)
    try:
        if args.command == "faq":
            # ID는 서버 카탈로그에서 얻으며 DB·검색기·LLM을 만들지 않는다.
            catalog = load_faq_catalog()
            if args.faq_id:
                result = catalog.answer(
                    FaqSelection(
                        request_id=uuid4(),
                        faq_id=args.faq_id,
                    )
                )
                output = result.model_dump(mode="json")
            else:
                output = [
                    dict(
                        topic=topic.model_dump(mode="json"),
                        questions=[
                            q.model_dump(mode="json")
                            for q in catalog.list_questions(topic.topic_id)
                        ],
                    )
                    for topic in catalog.list_topics()
                ]
        else:
            # 자연어 해석을 생략하고 직접 지정한 검색어·조건을 서버 검증 경계에 전달한다.
            conditions = ChatSearchConditions(
                asset_id=args.asset_id,
                date_from=args.date_from,
                date_to=args.date_to,
                limit=args.limit,
            )
            knowledge = get_chat_knowledge()
            if args.command == "search":
                hits = knowledge.search(
                    ChatSearchQuery(
                        query=args.query,
                        kind=args.kind,
                        conditions=conditions,
                        code=args.code,
                    ),
                    timeout_s=args.timeout,
                )
                output = dict(
                    count=len(hits),
                    note="유사 검색 결과 개수이며 전체 보고서 수가 아닙니다.",
                    hits=[hit.model_dump(mode="json") for hit in hits],
                )
            else:
                output = knowledge.query_history(
                    ChatHistoryQuery(conditions=conditions, code=args.code),
                    timeout_s=args.timeout,
                ).model_dump(mode="json")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        # 연결 예외에 인증 정보가 포함될 수 있어 예외 본문은 표시하지 않는다.
        print(f"기능 확인 실패: {type(exc).__name__}")
        return 1
    finally:
        if args.command != "faq":
            # 이 CLI는 단일 실행이므로 출력 후 공유 Qdrant를 닫고 폴더 잠금을 반환한다.
            close_rag_resources()


if __name__ == "__main__":
    raise SystemExit(main())
