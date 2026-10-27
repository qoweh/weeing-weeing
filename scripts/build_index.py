"""문서 목록(DB)과 벡터 DB를 맞춘다. 바뀐 문서만 다시 색인한다.

순서: RAG_CATALOG(data/catalog.toml) → DB document 테이블에 seed로 반영
      → DB의 문서 목록(seed + 완료된 업로드) → 벡터 DB 동기화 → 결과를 DB에 기록
입력: .env(DATABASE_URL·VECTOR_STORE·EMBEDDING_MODEL·QDRANT_* 등), 업로드 원본은 UPLOAD_DIR
출력: 벡터 DB(QDRANT_PATH 폴더·Qdrant 서버·CHROMA_DIR), 터미널에 결과 표
종료 코드: 0 성공 / 1 실패한 문서 있음 / 2 설정·DB·잠금·Indexer 문제로 시작 못 함

    make index                    # = PYTHONPATH=src uv run --no-sync python scripts/build_index.py
    make index ARGS=--dry-run     # 무엇이 바뀔지만 출력(모델을 올리지 않는다)
    make index ARGS=--force       # 바뀌지 않은 문서도 다시 색인(청킹·파서 변경 시)
    make index ARGS=--recreate    # 컬렉션을 새로 만들고 전부 색인(모델·차원·토크나이저 변경 시)
"""

import argparse
import json
import sys
from pathlib import Path

from weeing_weeing.config import from_root, get_settings
from weeing_weeing.contracts import DocumentRecord
from weeing_weeing.db import interface as db
from weeing_weeing.rag import factory
from weeing_weeing.rag.registry import catalog_from_records, seed_records
from weeing_weeing.rag.store import StoreMismatchError
from weeing_weeing.rag.sync import SyncReport, sync


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


LEGACY_MANIFEST = "metadata.json"  # #58까지 업로드 상태를 담던 파일


def import_legacy_uploads(upload_dir: Path, documents) -> list[str]:
    """예전 업로드 매니페스트(완료된 것)를 DB로 옮기고 파일 이름을 바꾼다. 한 번만 일어난다.

    옮기지 않으면 그 문서는 DB 목록에 없어서 이번 make index가 벡터 DB에서 지운다.
    깨진 매니페스트는 경고 문구로 돌려주고 그대로 둔다.
    """
    messages = []
    for path in sorted(upload_dir.glob(f"*/{LEGACY_MANIFEST}")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("status") == "completed":
                upload_id = raw["upload_id"]
                if documents.get_upload(upload_id) is None:
                    documents.add_upload(
                        DocumentRecord(
                            doc_id=raw["doc_id"],
                            doc_version=raw["doc_version"],
                            doc_type=raw.get("doc_type", "manual"),
                            doc_status=raw.get("doc_status", "approved"),
                            origin="upload",
                            upload_id=upload_id,
                            title=raw.get("title") or raw["source"],
                            source=f"{path.parent.name}/{raw['source']}",
                            source_sha256=raw["source_sha256"],
                            file_size=raw.get("file_size"),
                            extra={"asset_id": raw["asset_id"]}
                            if raw.get("asset_id")
                            else {},
                            uploaded_at=raw.get("uploaded_at"),
                            status="processing",
                        )
                    )
                    done = documents.complete_upload(
                        upload_id, chunk_count=raw.get("chunk_count") or 0
                    )
                    messages.append(
                        f"예전 업로드 {upload_id}({raw['doc_id']})를 DB로 옮김: {done.status}"
                    )
            path.rename(path.with_name(LEGACY_MANIFEST + ".imported"))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messages.append(f"예전 업로드 {path.parent.name}: 옮기지 못함 ({exc})")
    return messages


def _cannot_start(exc: object) -> int:
    print(f"시작하지 못함: {exc}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--catalog", type=Path, help="카탈로그 파일(기본: .env의 RAG_CATALOG)"
    )
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
        catalog_path = args.catalog or from_root(settings.rag_catalog)
        seeds = seed_records(catalog_path)  # 카탈로그 문제는 CatalogError로 멈춘다
        documents = db.open_documents(
            settings.database_url, timeout_s=settings.db_timeout_s
        )
        if args.dry_run:  # DB를 바꾸지 않는다: 카탈로그 + DB의 완료된 업로드
            records = seeds + [r for r in documents.listed() if r.origin != "seed"]
        else:
            imported = import_legacy_uploads(from_root(settings.upload_dir), documents)
            seeded = documents.sync_seed(seeds)
            records = documents.listed()
        warnings: list[str] = []
        catalog = catalog_from_records(
            records,
            seed_root=catalog_path.parent,
            upload_dir=from_root(settings.upload_dir),
            warnings=warnings,
        )
        make_indexer = None if args.dry_run else factory.indexer_class()
        # 모델은 첫 임베딩 때 올라온다(LazyEmbedder). dry-run은 모델을 올리지 않는다.
        store = factory.build_store(settings, recreate=args.recreate)
    except db.DatabaseUnavailableError as exc:
        return _cannot_start(
            f"DB에 연결하지 못함: {exc}\n"
            "  make db-up으로 PostgreSQL을 켜거나, Docker 없이 쓰려면 "
            ".env에 DATABASE_URL=sqlite:///storage/dev.db"
        )
    except (
        ValueError,  # 설정값 형식, CatalogError, StoreConfigError
        factory.StoreLockedError,
        StoreMismatchError,
        NotImplementedError,
    ) as exc:
        return _cannot_start(exc)
    except Exception as exc:  # 서버 연결 실패·타임아웃 등
        return _cannot_start(f"저장소에 연결하지 못함({type(exc).__name__}): {exc}")

    if not args.dry_run:
        print(
            f"DB 문서 목록: 카탈로그 추가 {len(seeded.added)} · 수정 {len(seeded.updated)}"
            f" · 삭제 {len(seeded.removed)}"
        )
        warnings += imported
        warnings += [
            f"업로드 {u}: 카탈로그 문서와 doc_id가 같아 대체됨"
            for u in seeded.superseded
        ]
    for warning in warnings:  # 업로드 문제는 건너뛰고 알리기만 한다
        print(f"경고: {warning}", file=sys.stderr)
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
            still_listed=None
            if args.dry_run
            else lambda doc_id: any(r.doc_id == doc_id for r in documents.listed()),
        )
    except Exception as exc:
        return _cannot_start(f"저장소 상태를 읽지 못함({type(exc).__name__}): {exc}")
    finally:
        store.close()  # 로컬 폴더 잠금을 푼다
    print(("[dry-run] " if args.dry_run else "") + "결과")
    print(format_report(report))
    if not args.dry_run:
        try:
            documents.record_index_results(
                report.added + report.updated + report.unchanged, report.failed
            )
        except db.DatabaseUnavailableError as exc:  # 색인은 끝났다. 기록만 못 했다
            print(f"경고: 색인 결과를 DB에 기록하지 못함: {exc}", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
