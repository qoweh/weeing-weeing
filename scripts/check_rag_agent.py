"""o02 한 질문의 실제 Agent 응답을 검사한다. --execute는 Claude 유료 호출이다."""

import argparse
import dataclasses
import hashlib
import json
import math
import tempfile
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from weeing_weeing.agent.interface import get_chat_service, get_llm_client
from weeing_weeing.api.chat_knowledge import DatabaseChatKnowledge
from weeing_weeing.config import get_settings
from weeing_weeing.contracts import (
    ChatContext,
    ChatQuestion,
    ChatSearchConditions,
    DocumentRecord,
)
from weeing_weeing.contracts.chat_tools import ChatSearchQuery
from weeing_weeing.db.interface import open_documents, open_reports
from weeing_weeing.rag import factory
from weeing_weeing.rag.e2e import EvaluationEmbedder, load_queries
from weeing_weeing.rag.eval_corpus import file_sha256, load_corpus
from weeing_weeing.rag.eval_sync import sync


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class MeasuredRetriever:
    """실제 검색기를 위임하고 로컬 평가용 ID·관련도만 기록한다."""

    def __init__(self, retriever):
        self.retriever = retriever
        self.phase = "preflight"
        self.calls = []

    def search_hits(self, query, **kwargs):
        started = time.monotonic()
        hits = self.retriever.search_hits(query, **kwargs)
        self.calls.append(
            {
                "phase": self.phase,
                "query": query,
                "elapsed_s": time.monotonic() - started,
                "hits": [
                    {"id": h.chunk.chunk_id, "relevance": h.relevance} for h in hits
                ],
            }
        )
        return hits


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 600:
        parser.error("시간 예산은 0초 초과 600초 이하여야 한다")
    settings = dataclasses.replace(
        get_settings(), rag_min_relevance=0.02, agent_max_turns=4
    )
    query = next(
        q for q in load_queries("data/eval/rag_queries_v1.toml") if q.id == "o02"
    )
    conditions = ChatSearchConditions(asset_id="BLDC-001", limit=5)
    plan = {
        "case": query.id,
        "question": query.text,
        "expected_statuses": ["INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE"],
        "model": settings.llm_model,
        "effort": settings.llm_effort,
        "minimum": settings.rag_min_relevance,
        "chunking": "structured",
        "candidate_k": settings.rag_candidate_k,
        "reranker_batch_size": 2,
        "asset_id": conditions.asset_id,
        "max_dialogue_turns": 4,
        "max_grounding_calls": 2,
        "max_application_calls": 6,
        "timeout_s": args.timeout,
        "executed": args.execute,
        "note": "SDK 내 최대 2회 재시도로 HTTP 요청 수·청구량은 더 클 수 있다. 운영 DB·색인은 사용하지 않는다.",
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if not args.execute:
        return 0
    if args.out is None:
        parser.error("실제 실행에는 새 --out 폴더가 필요하다")
    if not settings.reranker_model:
        parser.error("관련도 검증에 리랭커가 필요하다")
    args.out.mkdir(parents=True, exist_ok=False)
    write_json(args.out / "plan.json", plan)
    resources = ExitStack()
    with tempfile.TemporaryDirectory(prefix="rag-agent-") as temporary:
        folder = Path(temporary)
        settings = dataclasses.replace(
            settings,
            vector_store="qdrant",
            qdrant_url="",
            qdrant_path=folder / "qdrant",
        )
        try:
            corpus = load_corpus("data/eval/rag_documents_v1.toml")
            embedder = EvaluationEmbedder(factory.build_embedder(settings))
            store = factory.build_store(settings, embedder=embedder)
            resources.callback(store.close)
            indexed = sync(
                corpus, factory.indexer_class()(store, chunking="structured"), store
            )
            if not indexed.ok:
                raise ValueError("초기 색인 실패")
            url = f"sqlite:///{folder / 'evaluation.sqlite'}"
            documents = open_documents(url)
            resources.callback(documents._engine.dispose)
            reports = open_reports(url)
            resources.callback(reports._engine.dispose)
            for entry in corpus.documents:
                upload_id = uuid4().hex
                documents.add_upload(
                    DocumentRecord(
                        doc_id=entry.doc_id,
                        doc_version=entry.doc_version,
                        doc_type=entry.doc_type,
                        doc_status=entry.status,
                        title=entry.title,
                        origin="upload",
                        upload_id=upload_id,
                        source=str(corpus.file(entry).resolve()),
                        source_sha256=file_sha256(corpus.file(entry)),
                        status="processing",
                        uploaded_at=datetime.now(UTC),
                        extra=entry.extra,
                    )
                )
                documents.complete_upload(
                    upload_id, chunk_count=store.documents()[entry.doc_id].chunk_count
                )
            retriever = MeasuredRetriever(
                factory.build_retriever(
                    settings,
                    store,
                    reranker=factory.build_reranker(settings, batch_size=2),
                )
            )
            knowledge = DatabaseChatKnowledge(retriever, documents, reports)
            # 잔존 후보를 먼저 확인한다. Agent 입력에 검색 결과를 강제로 넣지는 않는다.
            preflight = knowledge.search(
                ChatSearchQuery(query=query.text, kind="MANUAL", conditions=conditions),
                timeout_s=args.timeout,
            )
            write_json(
                args.out / "preflight.json",
                {
                    "returned": len(preflight),
                    "searches": retriever.calls,
                },
            )
            retriever.phase = "agent"
            client = get_llm_client(settings, entrypoint="rag-validation")
            resources.callback(client.close)
            service = get_chat_service(knowledge, client=client, settings=settings)
            question = ChatQuestion(
                request_id=uuid4(), question=query.text, conditions=conditions
            )
            print("실제 o02 Agent 호출 시작", flush=True)
            response = service.reply(
                question, context=ChatContext(), timeout_s=args.timeout
            )
            # 응답 원문은 Git에서 제외한 로컬 폴더에만 저장한다.
            write_json(args.out / "response.json", response.model_dump(mode="json"))
            usage = dataclasses.asdict(service.last_run) if service.last_run else None
            summary = {
                "status": response.status,
                "expected_status_match": response.status in plan["expected_statuses"],
                "failure": response.failure.model_dump() if response.failure else None,
                "parts_count": len(response.parts),
                "source_count": len(response.sources),
                "citations_current": all(
                    knowledge.is_searchable(s, timeout_s=5) for s in response.sources
                )
                if response.sources
                else None,
                "usage": usage,
                "searches": retriever.calls,
                "preflight_count": len(preflight),
                "documents_sha256": hashlib.sha256(
                    Path("data/eval/rag_documents_v1.toml").read_bytes()
                ).hexdigest(),
                "note": "단일 질문의 CLI 평가다. HTTP 인증·대화 저장·운영 데이터 전체를 검증한 것은 아니다.",
            }
            write_json(args.out / "summary.json", summary)
            print(
                json.dumps(
                    {
                        "status": response.status,
                        "expected_status_match": summary["expected_status_match"],
                        "llm_calls": len(service.last_run.calls)
                        if service.last_run
                        else None,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return 2 if response.status == "FAILED" else 0
        except Exception as exc:
            write_json(args.out / "failure.json", {"type": type(exc).__name__})
            print(f"Agent 평가 중단: {type(exc).__name__}", flush=True)
            return 2
        finally:
            try:
                resources.close()
            except Exception as exc:
                write_json(
                    args.out / "cleanup_failure.json", {"type": type(exc).__name__}
                )
                print(f"평가 자원 정리 실패: {type(exc).__name__}", flush=True)
                return 2


if __name__ == "__main__":
    raise SystemExit(main())
