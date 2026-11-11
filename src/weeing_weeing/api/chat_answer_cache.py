"""지정한 독립 문서 질문의 응답 재사용 정책. 실제 응답은 기존 대화 DB가 보관한다."""

import hashlib
import json

from weeing_weeing.api.chat_knowledge import get_chat_knowledge
from weeing_weeing.config import get_settings

CACHED_QUESTIONS = (
    "M10 에러가 뭔지 설명해줘",
    "M10 에러가 발생하면 어떤 순서로 점검해야 해?",
    "M08 에러가 뭔지 설명해줘",
    "M18 에러가 뭔지 설명해줘",
    "M10 에러와 관련된 안전 주의사항을 알려줘",
    "전압이 상승했는데 어떻게 해야해?",
)


def answer_cache_scope(request):
    question = request.submission.question.strip()
    if question not in CACHED_QUESTIONS:
        return None
    settings = get_settings()
    documents = get_chat_knowledge().documents.listed()
    payload = {
        "policy": "m10-answer-v1",
        "question": question,
        "conditions": request.conditions.model_dump(mode="json"),
        "model": request.submission.model or settings.llm_model,
        "effort": settings.chat_llm_effort or settings.llm_effort,
        "review_model": settings.chat_review_model or settings.llm_model,
        "review_effort": settings.chat_review_effort,
        "documents": sorted(
            (
                d.doc_id,
                d.doc_version,
                d.source_sha256,
                d.status,
                d.doc_status,
                d.doc_type,
                d.title,
                sorted(d.extra.items()),
            )
            for d in documents
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def reusable_answer(response):
    return (
        response.status == "OK"
        and response.intent == "MANUAL"
        and bool(response.sources)
        and all(s.kind == "DOCUMENT" for s in response.sources)
        and all(p.kind == "MANUAL" for p in response.parts)
    )


def sources_current(response):
    return all(get_chat_knowledge().are_searchable(response.sources, timeout_s=5))
