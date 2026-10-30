"""새 질의에서 고정 하한을 검증한다. --execute 전에는 모델을 호출하지 않는다."""

import argparse
import dataclasses
import gc
import hashlib
import json
import math
import tempfile
from pathlib import Path

from weeing_weeing.config import get_settings
from weeing_weeing.rag import factory
from weeing_weeing.rag.e2e import EvaluationEmbedder, is_hit, load_queries
from weeing_weeing.rag.eval_corpus import load_corpus
from weeing_weeing.rag.eval_sync import sync


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def assess(query, hits, *, minimum, k):
    """한 번 채점한 동일 후보에서 하한 적용 후 최종 k개를 선택한다."""
    if any(h.relevance is None or not math.isfinite(h.relevance) for h in hits):
        raise ValueError("관련도 누락 또는 비정상 값")
    selected = [h for h in hits if minimum is None or h.relevance >= minimum][:k]
    rank = next((i for i, h in enumerate(selected, 1) if is_hit(h.chunk, query)), None)
    return {
        "minimum": minimum,
        "rank": rank,
        "returned": len(selected),
        "ids": [h.chunk.chunk_id for h in selected],
    }


def summarize(records, minimum):
    holdout = [r for r in records if not r["control"]]
    positive = [r for r in holdout if not r["expect_no_evidence"]]
    negative = [r for r in holdout if r["expect_no_evidence"]]

    def outcome(record):
        return next(o for o in record["outcomes"] if o["minimum"] == minimum)

    ranks = [outcome(r)["rank"] for r in positive]
    return {
        "positive": len(positive),
        "hit1": sum(rank == 1 for rank in ranks),
        "hit5": sum(rank is not None for rank in ranks),
        "mrr": sum(1 / rank for rank in ranks if rank) / len(ranks) if ranks else None,
        "positive_empty": sum(outcome(r)["returned"] == 0 for r in positive),
        "negative": len(negative),
        "rejected": sum(outcome(r)["returned"] == 0 for r in negative),
    }


def markdown(plan, records, *, complete):
    lines = [
        "# 새 질의 관련도 기준값 검증",
        "",
        f"- 측정 완료: {complete}; 보류 질의 {plan['holdout_count']}개 + 기존 o02 대조 1개",
        "- Qdrant 임시 저장소, 구조 기반 청킹, 동일한 리랭커 후보를 한 번 채점한다.",
        "- 후보를 관련도순으로 정렬한 뒤 하한 이상만 남기고 최종 5개를 선택한다.",
        "- o02는 기존에 사용한 질문으로 보류셋 집계에서 제외한다.",
        "- 이 보류셋으로 기준값을 다시 조정하지 않는다. 문서·의미 범주 독립 검증은 아니다.",
        "",
        "| 하한 | Hit@1 | Hit@5 | MRR | 정상 빈 결과 | 범위 밖 거절 |",
        "|---|---|---|---|---|---|",
    ]
    for minimum in (None, plan["minimum"]):
        value = summarize(records, minimum)
        mrr = f"{value['mrr']:.3f}" if value["mrr"] is not None else "미측정"
        lines.append(
            f"| {minimum} | {value['hit1']}/{value['positive']} | "
            f"{value['hit5']}/{value['positive']} | {mrr} | {value['positive_empty']} | "
            f"{value['rejected']}/{value['negative']} |"
        )
    lines += [
        "",
        "## 질의별 결과",
        "",
        "| ID | 근거 없음 정답 | 하한 | 정답 순위 | 반환 수 | 1위 관련도 |",
        "|---|---|---|---|---|---|",
    ]
    for record in records:
        score = record["hits"][0]["relevance"] if record["hits"] else None
        for outcome in record["outcomes"]:
            lines.append(
                f"| {record['id']} | {record['expect_no_evidence']} | {outcome['minimum']} | "
                f"{outcome['rank']} | {outcome['returned']} | {score} |"
            )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queries", type=Path, default=Path("data/eval/rag_queries_holdout_v1.toml")
    )
    parser.add_argument(
        "--documents", type=Path, default=Path("data/eval/rag_documents_v1.toml")
    )
    parser.add_argument("--minimum", type=float, default=0.02)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not math.isfinite(args.minimum):
        parser.error("하한은 유한한 수여야 한다")
    queries = load_queries(args.queries)
    if not any(q.expect_no_evidence for q in queries) or not any(
        not q.expect_no_evidence for q in queries
    ):
        parser.error("정상 질문과 근거 없음 질문이 각각 1개 이상 필요하다")
    previous = load_queries("data/eval/rag_queries_v1.toml")
    if {q.text for q in queries} & {q.text for q in previous}:
        parser.error("기존 평가 질의와 중복된 문장이 있다")
    control = next(q for q in previous if q.id == "o02")
    settings = get_settings()
    if settings.rag_candidate_k < 5 or not settings.reranker_model:
        parser.error("후보 수 5 이상과 리랭커가 필요하다")
    plan = {
        "queries_sha256": hashlib.sha256(args.queries.read_bytes()).hexdigest(),
        "documents_sha256": hashlib.sha256(args.documents.read_bytes()).hexdigest(),
        "holdout_count": len(queries),
        "minimum": args.minimum,
        "candidate_k": settings.rag_candidate_k,
        "k": 5,
        "chunking": "structured",
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "reranker_batch_size": 2,
        "thresholds": [None, args.minimum],
        "executed": args.execute,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if not args.execute:
        return 0
    if args.out is None:
        parser.error("실제 실행에는 새 --out 폴더가 필요하다")
    args.out.mkdir(parents=True, exist_ok=False)
    save(args.out / "plan.json", plan)
    records = []
    with tempfile.TemporaryDirectory(prefix="rag-holdout-") as temporary:
        settings = dataclasses.replace(
            settings,
            qdrant_url="",
            qdrant_path=Path(temporary) / "qdrant",
            vector_store="qdrant",
            rag_min_relevance=None,
        )
        embedder = EvaluationEmbedder(factory.LazyEmbedder(settings.embedding_model))
        store = factory.build_store(settings, embedder=embedder)
        try:
            corpus = load_corpus(args.documents)
            indexed = sync(
                corpus, factory.indexer_class()(store, chunking="structured"), store
            )
            if not indexed.ok:
                raise ValueError("초기 색인 실패")
            plan["chunk_counts"] = {
                key: info.chunk_count for key, info in store.documents().items()
            }
            save(args.out / "plan.json", plan)
            all_queries = [*queries, control]
            for query in all_queries:
                embedder.embed_query(query.text)
            embedder.freeze()
            gc.collect()
            retriever = factory.build_retriever(
                settings, store, reranker=factory.build_reranker(settings, batch_size=2)
            )
            for i, query in enumerate(all_queries, 1):
                print(f"질의 {i}/{len(all_queries)} {query.id} 시작", flush=True)
                hits = retriever.search_hits(
                    query.text, k=settings.rag_candidate_k, filters=query.where
                )
                record = {
                    "id": query.id,
                    "control": query is control,
                    "expect_no_evidence": query.expect_no_evidence,
                    "outcomes": [
                        assess(query, hits, minimum=m, k=5)
                        for m in (None, args.minimum)
                    ],
                    "hits": [
                        {
                            "id": h.chunk.chunk_id,
                            "doc_id": h.chunk.doc_id,
                            "text": h.chunk.text,
                            "relevance": h.relevance,
                            "rrf": h.score,
                        }
                        for h in hits
                    ],
                }
                records.append(record)
                save(
                    args.out / "results.json",
                    {"plan": plan, "complete": False, "records": records},
                )
                (args.out / "report.md").write_text(
                    markdown(plan, records, complete=False), encoding="utf-8"
                )
                print(f"질의 {i}/{len(all_queries)} {query.id} 완료", flush=True)
        except Exception as exc:
            save(
                args.out / "failure.json",
                {"type": type(exc).__name__, "completed": len(records)},
            )
            print(f"평가 중단: {type(exc).__name__}", flush=True)
            return 2
        finally:
            store.close()
    save(
        args.out / "results.json", {"plan": plan, "complete": True, "records": records}
    )
    (args.out / "report.md").write_text(
        markdown(plan, records, complete=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {str(m): summarize(records, m) for m in (None, args.minimum)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
