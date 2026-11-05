"""무과금 Langfuse 기록 확인용 재생 LLM·샘플 지식 (#206).

실제 ClaudeClient의 기록 경로(generation 이름·토큰·metadata)를 그대로 타되, SDK 자리에
정해진 응답을 돌려주는 ReplaySdk를 넣는다. Anthropic·Voyage를 부르지 않으므로 비용이 없다.

- 도구 루프: 1턴은 질문으로 search_knowledge(MANUAL)를 부르고, 다음 턴은 직전 도구 결과의
  첫 출처를 인용해 OK로 제출한다. 결과가 없으면 INSUFFICIENT_EVIDENCE로 제출한다.
- 근거 검토(generate_json): 항상 SUPPORTED.
- SampleKnowledge: DB·Qdrant 없이 고정 문서 몇 개를 글자 겹침으로 고른다.
  실제 검색 경로를 확인할 때는 스크립트가 hashing 임베딩의 실제 지식 조회를 넘긴다.
"""

import json
from types import SimpleNamespace
from typing import Any

from weeing_weeing.contracts.chat import ChatDocumentSource
from weeing_weeing.contracts.chat_tools import ChatSearchHit

REPLAY_MODEL = "replay-no-cost"

_SAMPLES = (
    (
        "SMOKE-MAN-1",
        "입구 센서 점검",
        "입구 센서 장기 점유 시 센서 렌즈 오염과 배선 체결을 확인한다.",
    ),
    (
        "SMOKE-MAN-2",
        "모터 과열 점검",
        "모터 외함 온도가 기준을 넘으면 냉각 팬과 부하 전류를 확인한다.",
    ),
    (
        "SMOKE-MAN-3",
        "벨트 장력 점검",
        "이송 속도가 떨어지면 벨트 장력과 풀리 마모 상태를 확인한다.",
    ),
)


def _block(**fields: Any) -> SimpleNamespace:
    block = SimpleNamespace(**fields)
    block.model_dump = lambda: dict(fields)
    return block


def _message(blocks: list[SimpleNamespace], stop_reason: str) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return SimpleNamespace(
        content=blocks, stop_reason=stop_reason, usage=usage, model=REPLAY_MODEL
    )


class ReplaySdk:
    """anthropic.Anthropic 자리에 들어가는 재생 SDK. 네트워크를 쓰지 않는다."""

    def __init__(self) -> None:
        self.calls = 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def with_options(self, **_: Any) -> "ReplaySdk":
        return self

    def close(self) -> None:
        pass

    def _create(self, **params: Any) -> SimpleNamespace:
        self.calls += 1
        if "tools" not in params:  # 근거 검토
            verdict = '{"verdict":"SUPPORTED","unsupported_parts":[]}'
            return _message([_block(type="text", text=verdict)], "end_turn")
        messages = params["messages"]
        if not any(m["role"] == "assistant" for m in messages):
            task = json.loads(messages[0]["content"])
            use = _block(
                type="tool_use",
                id=f"replay-{self.calls}",
                name="search_knowledge",
                input={"query": task["question"], "kind": "MANUAL"},
            )
            return _message([use], "tool_use")
        return _message([self._submit(messages)], "tool_use")

    def _submit(self, messages: list[dict[str, Any]]) -> SimpleNamespace:
        hits: list[dict[str, Any]] = []
        for item in reversed(messages[-1]["content"]):
            if isinstance(item, dict) and item.get("type") == "tool_result":
                try:
                    result = json.loads(item["content"]) if not item["is_error"] else []
                    hits = (
                        result.get("hits", []) if isinstance(result, dict) else result
                    )
                except (TypeError, ValueError):
                    hits = []
                break
        if hits:
            first = hits[0]
            answer = {
                "intent": "MANUAL",
                "status": "OK",
                "message": "검색 근거를 바탕으로 안내합니다.",
                "parts": [
                    {
                        "kind": "MANUAL",
                        "text": first["text"][:500],
                        "source_ids": [first["source"]["source_id"]],
                    }
                ],
                "clarification_questions": [],
            }
        else:
            answer = {
                "intent": "MANUAL",
                "status": "INSUFFICIENT_EVIDENCE",
                "message": "기록 확인용 검색에서 질문과 관련된 매뉴얼을 찾지 못했습니다.",
                "parts": [],
                "clarification_questions": [],
            }
        return _block(
            type="tool_use",
            id=f"replay-{self.calls}",
            name="submit_answer",
            input=answer,
        )


class SampleKnowledge:
    """DB·검색 서버 없는 고정 매뉴얼 3건. 질문과 글자가 많이 겹치는 순서로 반환한다."""

    def _hits(self) -> dict[str, ChatSearchHit]:
        return {
            doc_id: ChatSearchHit(
                source=ChatDocumentSource(
                    source_id=f"{doc_id}:1",
                    title=title,
                    doc_id=doc_id,
                    doc_version="1",
                    section=title,
                ),
                text=text,
            )
            for doc_id, title, text in _SAMPLES
        }

    def validate_query(self, query, *, timeout_s: float) -> None:
        return None

    def search(self, query, *, timeout_s: float) -> list[ChatSearchHit]:
        if query.kind != "MANUAL":
            return []
        words = set(query.query.split())

        def overlap(hit: ChatSearchHit) -> int:
            return sum(word in hit.text or word in hit.source.title for word in words)

        ranked = sorted(self._hits().values(), key=overlap, reverse=True)
        return [hit for hit in ranked if overlap(hit) > 0][: query.conditions.limit]

    def query_history(self, query, *, timeout_s: float):
        raise RuntimeError("기록 확인용 샘플에는 정비이력이 없다")

    def query_incidents(self, query, *, timeout_s: float):
        raise RuntimeError("기록 확인용 샘플에는 사건이 없다")

    def is_searchable(self, source, *, timeout_s: float) -> bool:
        return source.doc_id in self._hits()


def get_replay_llm_client(settings, *, entrypoint: str = "trace-smoke"):
    """Langfuse 기록은 실제와 같고 Claude 호출만 재생하는 클라이언트."""
    from weeing_weeing.agent.claude import ClaudeClient
    from weeing_weeing.agent.tracing import build_tracer

    return ClaudeClient(
        REPLAY_MODEL,
        effort=settings.llm_effort,
        sdk=ReplaySdk(),
        tracer=build_tracer(settings, entrypoint=entrypoint),
    )
