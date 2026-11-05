"""Claude·Voyage 호출 없이 챗봇 질문 1건을 실행해 Langfuse 기록 모양을 확인한다 (#206).

LLM은 정해진 응답을 재생하고(비용 0), 기록만 Langfuse로 보낸다. 기본은 DB·검색 서버가
필요 없는 샘플 지식이다. --real-knowledge는 프로젝트 DB·벡터 색인을 쓰며, 비용이 없도록
EMBEDDING_PROVIDER=hashing이고 리랭커가 꺼져 있을 때만 실행한다.

기록은 기본으로 environment=test에 남아 dev·demo 기록과 섞이지 않는다.
"""

import argparse
import dataclasses
import sys
from uuid import uuid4

from weeing_weeing.agent.interface import (
    get_chat_service,
    get_replay_llm_client,
    replay_sample_knowledge,
    trace_session,
)
from weeing_weeing.config import get_settings
from weeing_weeing.contracts import ChatContext, ChatQuestion


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="입구 센서 점검 방법 알려줘")
    parser.add_argument("--environment", default="test", help="Langfuse environment")
    parser.add_argument("--session", help="묶을 세션 ID(같은 값으로 여러 번 실행)")
    parser.add_argument(
        "--real-knowledge",
        action="store_true",
        help="프로젝트 DB·벡터 색인 사용(hashing·리랭커 꺼짐일 때만)",
    )
    args = parser.parse_args(argv)

    settings = dataclasses.replace(
        get_settings(), langfuse_tracing_environment=args.environment
    )
    if args.real_knowledge:
        if settings.embedding_provider != "hashing" or settings.reranker_model:
            print(
                "--real-knowledge는 비용이 없도록 EMBEDDING_PROVIDER=hashing, "
                "RERANKER_MODEL 비움일 때만 실행한다.",
                file=sys.stderr,
            )
            return 2
        from weeing_weeing.api.chat_knowledge import get_chat_knowledge

        knowledge = get_chat_knowledge()
    else:
        knowledge = replay_sample_knowledge()

    client = get_replay_llm_client(settings)
    service = get_chat_service(knowledge, client=client, settings=settings)
    question = ChatQuestion(request_id=uuid4(), question=args.question)
    try:
        with trace_session(args.session):
            response = service.reply(question, context=ChatContext(), timeout_s=60)
    finally:
        client.close()  # 기록을 보내고 끝낸다

    run = service.last_run
    print(f"status={response.status} llm_calls={len(run.calls) if run else 0}")
    print(f"request_id={question.request_id} environment={args.environment}")
    if not getattr(client.tracer, "enabled", False):
        print("Langfuse 설정이 없어 기록하지 않았다(LANGFUSE_BASE_URL·키 확인).")
    else:
        session = args.session or str(question.request_id)
        print(
            f"Langfuse에서 environment={args.environment}를 고르고 세션 {session}으로 찾는다"
            + (" (요청 ID는 trace metadata.run_id)." if args.session else ".")
        )
        print(
            "안 보이면 셸에 export된 LANGFUSE_* 값이 .env보다 우선해 다른 프로젝트로"
            " 갔는지 확인한다(docs/USAGE_TRACKING.md)."
        )
    return 0 if response.status != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
