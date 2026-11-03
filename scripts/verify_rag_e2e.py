"""실제 문서 E2E 검증(#28). 평가 자료 목록 문서를 백엔드마다 새 저장소에 색인하고 비교한다.

입력: data/eval/rag_documents_v1.toml과 그 문서들, data/eval/rag_queries_v1.toml(샘플 질의),
.env(EMBEDDING_MODEL 등)
출력: 터미널 요약, outputs/rag_e2e/report-<시각>.md(검색 비교표·색인·갱신·질의별 상위 결과)
종료 코드: 0 모든 검사 통과 / 1 색인·멱등·갱신 검사 실패 / 2 설정·연결·실행 오류

    make rag-e2e                                      # Qdrant 로컬 + Chroma
    make rag-e2e ARGS="--backends qdrant,chroma,qdrant-server"   # 서버도(make qdrant-up 먼저)

- 저장소는 백엔드마다 임시 폴더(서버는 임시 컬렉션)에 새로 만들고 끝나면 지운다.
  storage/의 실제 색인은 건드리지 않는다.
- 임베딩 모델은 한 번만 올려 모든 백엔드가 같이 쓴다.
- 같은 입력의 임베딩을 실행 중 재사용한다. 순수 처리 시간 측정은 --no-embedding-cache.
- RERANKER_MODEL이 있으면 로컬 리랭커도 한 번만 올려 reranked 결과를 비교한다.
- 실제 색인에는 #6 Indexer가 rag/factory.py의 indexer_class()에 연결돼 있어야 한다.
"""

import argparse
import dataclasses
import gc
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from pathlib import Path

from weeing_weeing.config import get_settings
from weeing_weeing.rag import factory
from weeing_weeing.rag.e2e import (
    EvaluationEmbedder,
    format_markdown,
    load_queries,
    run_backend,
)
from weeing_weeing.rag.eval_corpus import load_corpus

BACKENDS = ("qdrant", "chroma", "qdrant-server")


def _settings_for(backend: str, base, tmp: Path):
    if backend == "qdrant":
        return dataclasses.replace(
            base, vector_store="qdrant", qdrant_url="", qdrant_path=tmp / "qdrant"
        )
    if backend == "chroma":
        return dataclasses.replace(
            base, vector_store="chroma", chroma_dir=tmp / "chroma"
        )
    return dataclasses.replace(  # qdrant-server: 임시 컬렉션
        base, vector_store="qdrant", rag_collection=f"e2e_{uuid.uuid4().hex[:10]}"
    )


def _drop_server_collection(settings) -> None:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=settings.qdrant_url, timeout=settings.qdrant_timeout_s)
    client.delete_collection(settings.rag_collection)
    client.close()


def _cannot_start(message: object) -> int:
    print(f"시작하지 못함: {message}", file=sys.stderr)
    return 2


@contextmanager
def _temporary_store(backend: str) -> Iterator[Path]:
    temporary = tempfile.TemporaryDirectory(prefix=f"rag-e2e-{backend}-")
    path = Path(temporary.name).resolve()
    if not path.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError("임시 저장소가 지정된 임시 폴더 밖에 있습니다.")
    try:
        yield path
    finally:
        # Chroma의 Rust SQLite 연결은 close 직후에도 잠시 파일을 잡을 수 있다.
        # 정리는 짧게 재시도하고, 계속 실패하면 예외를 숨기지 않는다.
        for attempt in range(5):
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--documents", type=Path, default=Path("data/eval/rag_documents_v1.toml")
    )
    parser.add_argument(
        "--queries", type=Path, default=Path("data/eval/rag_queries_v1.toml")
    )
    parser.add_argument("--backends", default="qdrant,chroma", help=",".join(BACKENDS))
    parser.add_argument("-k", type=int, default=5, help="상위 몇 개를 볼지")
    parser.add_argument("--out", type=Path, help="결과 파일(기본 outputs/rag_e2e/)")
    parser.add_argument(
        "--chunking",
        choices=("legacy", "structured"),
        default="legacy",
        help="문서 청킹 방식(기본 legacy, 웹 신규 업로드는 structured)",
    )
    parser.add_argument(
        "--no-embedding-cache",
        action="store_true",
        help="같은 입력도 다시 임베딩한다(캐시 없는 처리 시간 측정)",
    )
    parser.add_argument(
        "--keep-embedding-model",
        action="store_true",
        help="임베딩 캐시를 사용해도 검색 중 모델을 메모리에 유지한다",
    )
    parser.add_argument(
        "--reranker-batch-size", type=int, default=16, help="리랭커 추론 배치 크기"
    )
    args = parser.parse_args(argv)
    if args.reranker_batch_size < 1:
        parser.error("--reranker-batch-size는 1 이상이어야 한다")

    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    unknown = sorted(set(backends) - set(BACKENDS))
    if unknown:
        parser.error(f"알 수 없는 백엔드 {unknown}. 가능: {', '.join(BACKENDS)}")
    try:
        settings = get_settings()
        if "qdrant-server" in backends and not settings.qdrant_url:
            raise ValueError("qdrant-server는 QDRANT_URL이 필요하다(make qdrant-up)")
        corpus = load_corpus(args.documents)
        queries = load_queries(args.queries)
        make_indexer = partial(factory.indexer_class(), chunking=args.chunking)
        reranker = factory.build_reranker(settings, batch_size=args.reranker_batch_size)
    except NotImplementedError:
        return _cannot_start(
            "#6 Indexer가 아직 없다. rag/factory.py의 indexer_class()에 연결한 뒤 실행한다"
        )
    except ValueError as exc:
        return _cannot_start(exc)

    embedder = factory.LazyEmbedder(settings.embedding_model)  # 모델은 한 번만
    if not args.no_embedding_cache:
        embedder = EvaluationEmbedder(embedder)

    def prepare_search():
        print("질의 임베딩 사전 계산 시작", flush=True)
        for query in queries:
            embedder.embed_query(query.text)
        embedder.freeze()
        gc.collect()
        print("임베딩 캐시 고정·모델 참조 해제 완료", flush=True)

    freeze_embeddings = not args.no_embedding_cache and not args.keep_embedding_model
    runs = []
    skipped: dict[str, str] = {}  # 시작하지 못한 백엔드 → 이유. 나머지는 계속 돈다
    for backend in backends:
        with _temporary_store(backend) as tmp:
            run_settings = _settings_for(backend, settings, tmp)
            try:
                store = factory.build_store(run_settings, embedder=embedder)
            except Exception as exc:  # 설정 누락·서버 연결 실패 등
                skipped[backend] = f"{type(exc).__name__}: {exc}"
                print(f"[{backend}] 시작하지 못함: {skipped[backend]}", file=sys.stderr)
                continue
            try:
                print(f"[{backend}] 색인·검사 중...", flush=True)
                runs.append(
                    run_backend(
                        backend,
                        store,
                        corpus,
                        make_indexer,
                        queries,
                        k=args.k,
                        retriever=factory.build_retriever(
                            run_settings, store, reranker=reranker
                        )
                        if reranker is not None
                        else None,
                        progress=lambda message: print(message, flush=True),
                        prepare_search=prepare_search if freeze_embeddings else None,
                    )
                )
            except Exception as exc:
                skipped[backend] = f"{type(exc).__name__}: {exc}"
                print(f"[{backend}] 검증 실패: {skipped[backend]}", file=sys.stderr)
            finally:
                store.close()
                if backend == "qdrant-server":
                    _drop_server_collection(run_settings)

    report = format_markdown(runs, k=args.k)
    report += (
        "\n## 실행 설정\n\n"
        f"- 청킹 방식: `{args.chunking}`\n"
        f"- 질의 파일: `{args.queries}` ({len(queries)}개)\n"
        f"- 임베딩: `{settings.embedding_model}`\n"
        f"- 리랭커: `{settings.reranker_model or '미사용'}`\n"
        f"- 리랭커 추론 배치 크기: {args.reranker_batch_size}\n"
        f"- 후보 수: {settings.rag_candidate_k}, 최종 k: {args.k}\n"
        f"- 관련도 하한: {settings.rag_min_relevance}\n"
        f"- 실행 중 임베딩 캐시: {'미사용' if args.no_embedding_cache else '사용'}\n"
        f"- 질의 임베딩 사전 계산 후 모델 해제: {'사용' if freeze_embeddings else '미사용'}\n"
        "- 처리 시간은 위 캐시 설정을 포함한다. 캐시 사용 결과는 순수 추론 속도가 아니다.\n"
    )
    if skipped:
        report += "\n## 시작하지 못한 백엔드·검증 실패\n\n" + "".join(
            f"- {b}: {why}\n" for b, why in skipped.items()
        )
    out = args.out or Path("outputs/rag_e2e") / (
        f"report-{datetime.now():%Y%m%d-%H%M%S}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    for run in runs:
        best = " / ".join(f"{s.mode} {s.hit_at_k}/{s.total}" for s in run.summaries())
        print(
            f"[{run.backend}] 검사 {'통과' if run.ok else '실패'} · hit@{args.k} {best}"
        )
    print(f"결과 저장: {out}")
    if skipped:
        return 2
    return 0 if all(run.ok for run in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
