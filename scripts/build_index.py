"""카탈로그(data/catalog.toml)와 벡터 DB를 맞춘다. 바뀐 문서만 다시 색인한다.

입력: data/catalog.toml과 그 문서들, .env(VECTOR_STORE·EMBEDDING_MODEL·QDRANT_* 등)
출력: 벡터 DB(QDRANT_PATH 폴더·Qdrant 서버·CHROMA_DIR), 터미널에 결과 표
종료 코드: 0 성공 / 1 실패한 문서 있음 / 2 설정·잠금·Indexer 문제로 시작 못 함

    make index                    # = PYTHONPATH=src uv run --no-sync python scripts/build_index.py
    make index ARGS=--dry-run     # 무엇이 바뀔지만 출력(모델을 올리지 않는다)
    make index ARGS=--force       # 바뀌지 않은 문서도 다시 색인(청킹·파서 변경 시)
    make index ARGS=--recreate    # 컬렉션을 새로 만들고 전부 색인(모델·차원·토크나이저 변경 시)
"""

import argparse
import sys
from pathlib import Path

from weeing_weeing.config import get_settings
from weeing_weeing.rag import factory
from weeing_weeing.rag.catalog import load_catalog
from weeing_weeing.rag.store import StoreMismatchError
from weeing_weeing.rag.sync import SyncReport, sync

DEFAULT_CATALOG = Path("data/catalog.toml")


def format_report(report: SyncReport) -> str:
    rows = [
        ("added", report.added),
        ("updated", report.updated),
        ("unchanged", report.unchanged),
        ("removed", report.removed),
        ("failed", [f"{d} ({msg})" for d, msg in report.failed.items()]),
    ]
    lines = [f"{'구분':<10} {'수':>3}  문서"]
    lines += [f"{name:<10} {len(docs):>3}  {', '.join(docs)}" for name, docs in rows]
    return "\n".join(lines)


def _cannot_start(exc: object) -> int:
    print(f"시작하지 못함: {exc}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--dry-run", action="store_true", help="바뀔 내용만 출력")
    parser.add_argument("--force", action="store_true", help="모든 문서 다시 색인")
    parser.add_argument(
        "--recreate", action="store_true", help="컬렉션을 새로 만들고 전부 색인"
    )
    args = parser.parse_args(argv)
    if args.dry_run and args.recreate:
        parser.error("--recreate는 --dry-run과 함께 쓸 수 없다")

    try:
        settings = get_settings()  # QDRANT_TIMEOUT_S=abc 같은 값도 여기서 걸린다
        catalog = load_catalog(args.catalog)
        make_indexer = None if args.dry_run else factory.indexer_class()
        # 모델은 첫 임베딩 때 올라온다(LazyEmbedder). dry-run은 모델을 올리지 않는다.
        store = factory.build_store(settings, recreate=args.recreate)
    except (
        ValueError,  # 설정값 형식, CatalogError, StoreConfigError
        factory.StoreLockedError,
        StoreMismatchError,
        NotImplementedError,
    ) as exc:
        return _cannot_start(exc)
    except Exception as exc:  # 서버 연결 실패·타임아웃 등
        return _cannot_start(f"저장소에 연결하지 못함({type(exc).__name__}): {exc}")

    try:
        indexer = make_indexer(store) if make_indexer else None
        server = settings.vector_store == "qdrant" and settings.qdrant_url
        mode = "서버" if server else "로컬"
        print(
            f"저장소: {settings.vector_store}({mode}) / 컬렉션 {settings.rag_collection}"
        )
        # 문서별 실패는 sync가 report.failed에 모은다. 여기서 잡히는 것은 저장소 상태를
        # 읽지 못한 경우(연결 끊김 등)라서 "시작 못 함"으로 본다.
        report = sync(
            catalog,
            indexer,
            store,
            force=args.force or args.recreate,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        return _cannot_start(f"저장소 상태를 읽지 못함({type(exc).__name__}): {exc}")
    finally:
        store.close()  # 로컬 폴더 잠금을 푼다
    print(("[dry-run] " if args.dry_run else "") + "결과")
    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
