"""실제 문서 E2E 검증(#28). 카탈로그 문서를 백엔드마다 새 저장소에 색인하고 비교한다.

입력: data/catalog.toml과 그 문서들, data/eval/rag_queries_v1.toml(샘플 질의), .env(EMBEDDING_MODEL 등)
출력: 터미널 요약, outputs/rag_e2e/report-<시각>.md(검색 비교표·색인·갱신·질의별 상위 결과)
종료 코드: 0 모든 검사 통과 / 1 색인·멱등·갱신 검사 실패 / 2 설정·Indexer 문제로 시작 못 함

    make rag-e2e                                      # Qdrant 로컬 + Chroma
    make rag-e2e ARGS="--backends qdrant,chroma,qdrant-server"   # 서버도(make qdrant-up 먼저)

- 저장소는 백엔드마다 임시 폴더(서버는 임시 컬렉션)에 새로 만들고 끝나면 지운다.
  storage/의 실제 색인은 건드리지 않는다.
- 임베딩 모델은 한 번만 올려 모든 백엔드가 같이 쓴다.
- 실제 색인에는 #6 Indexer가 rag/factory.py의 indexer_class()에 연결돼 있어야 한다.
"""

import argparse
import dataclasses
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from weeing_weeing.config import get_settings
from weeing_weeing.rag import factory
from weeing_weeing.rag.catalog import load_catalog
from weeing_weeing.rag.e2e import format_markdown, load_queries, run_backend

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.toml"))
    parser.add_argument(
        "--queries", type=Path, default=Path("data/eval/rag_queries_v1.toml")
    )
    parser.add_argument("--backends", default="qdrant,chroma", help=",".join(BACKENDS))
    parser.add_argument("-k", type=int, default=5, help="상위 몇 개를 볼지")
    parser.add_argument("--out", type=Path, help="결과 파일(기본 outputs/rag_e2e/)")
    args = parser.parse_args(argv)

    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    unknown = sorted(set(backends) - set(BACKENDS))
    if unknown:
        parser.error(f"알 수 없는 백엔드 {unknown}. 가능: {', '.join(BACKENDS)}")
    try:
        settings = get_settings()
        if "qdrant-server" in backends and not settings.qdrant_url:
            raise ValueError("qdrant-server는 QDRANT_URL이 필요하다(make qdrant-up)")
        catalog = load_catalog(args.catalog)
        queries = load_queries(args.queries)
        make_indexer = factory.indexer_class()
    except NotImplementedError:
        return _cannot_start(
            "#6 Indexer가 아직 없다. rag/factory.py의 indexer_class()에 연결한 뒤 실행한다"
        )
    except ValueError as exc:
        return _cannot_start(exc)

    embedder = factory.LazyEmbedder(settings.embedding_model)  # 모델은 한 번만
    runs = []
    skipped: dict[str, str] = {}  # 시작하지 못한 백엔드 → 이유. 나머지는 계속 돈다
    for backend in backends:
        with tempfile.TemporaryDirectory(prefix=f"rag-e2e-{backend}-") as tmp:
            run_settings = _settings_for(backend, settings, Path(tmp))
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
                        backend, store, catalog, make_indexer, queries, k=args.k
                    )
                )
            finally:
                store.close()
                if backend == "qdrant-server":
                    _drop_server_collection(run_settings)

    report = format_markdown(runs, k=args.k)
    if skipped:
        report += "\n## 시작하지 못한 백엔드\n\n" + "".join(
            f"- {b}: {why}\n" for b, why in skipped.items()
        )
    out = args.out or Path("outputs/rag_e2e") / (
        f"report-{datetime.now():%Y%m%d-%H%M%S}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    for run in runs:
        best = {s.mode: f"{s.hit_at_k}/{s.total}" for s in run.summaries()}
        print(
            f"[{run.backend}] 검사 {'통과' if run.ok else '실패'} · "
            f"hit@{args.k} dense {best['dense']} / hybrid {best['hybrid']}"
        )
    print(f"결과 저장: {out}")
    if skipped:
        return 2
    return 0 if all(run.ok for run in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
