"""실제 Claude·공유 RAG·DB를 연결한 챗봇 단일 질문 실행. 대화 저장은 하지 않는다."""

import argparse
from uuid import uuid4

from weeing_weeing.api.chat_knowledge import build_chat_service
from weeing_weeing.config import get_settings
from weeing_weeing.contracts import ChatContext, ChatQuestion, ChatSearchConditions


def main(argv=None):
    """터미널 입력을 질문 계약으로 바꿔 실제 Claude·DB·RAG 조립 서비스에 전달한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--asset-id")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    args = parser.parse_args(argv)
    question = ChatQuestion(
        request_id=uuid4(),
        question=args.question,
        conditions=ChatSearchConditions(
            asset_id=args.asset_id, date_from=args.date_from, date_to=args.date_to
        ),
    )
    try:
        # CLI는 이전 대화를 저장하지 않으므로 빈 문맥으로 질문 한 건만 처리한다.
        result = build_chat_service().reply(
            question, context=ChatContext(), timeout_s=get_settings().llm_timeout_s
        )
    except Exception as exc:
        # 설정·DB 예외에 비밀값이 포함될 수 있어 예외 본문은 출력하지 않는다.
        print(f"챗봇 시작 실패: {type(exc).__name__}")
        return 2
    print(result.model_dump_json(indent=2))
    return 1 if result.status == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
