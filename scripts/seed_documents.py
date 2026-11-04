"""팀 문서(data/seed/documents_v1.toml)를 웹 업로드와 같은 방식으로 미리 등록·임베딩한다.

같은 파일이 이미 지금 컬렉션(RAG_COLLECTION)에 임베딩돼 있으면 건너뛴다(임베딩 비용 0).
EMBEDDING_PROVIDER=voyage면 처음 한 번은 Voyage API를 부른다(문서 3개·청크 약 90개, 10만 토큰 이하로 무료 범위 안).

    make seed-docs                       # 로컬
    ops/aws.sh seed-docs                 # 운영 서버(api 컨테이너 안에서 실행)
    ... --replace                        # 웹에서 다른 파일로 교체한 문서도 이 파일로 덮어씀
    ... --file data/seed/다른목록.toml

종료 코드: 0 전부 성공·건너뜀, 1 실패 문서 있음, 2 목록·설정 오류
"""

import argparse
import sys
from pathlib import Path

from weeing_weeing.api.document_seed import SeedResult, load_seed, seed_documents
from weeing_weeing.db import interface as db
from weeing_weeing.rag.interface import close_rag_resources

LABELS = {
    "added": "등록",
    "reindexed": "다시 임베딩",
    "replaced": "교체",
    "skipped": "건너뜀",
    "failed": "실패",
}


def _print(result: SeedResult) -> None:
    print(f"[{LABELS[result.action]}] {result.doc_id} {result.detail}".rstrip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--file", type=Path, default=Path("data/seed/documents_v1.toml")
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        items = load_seed(args.file)
    except (OSError, ValueError) as exc:
        print(f"시드 목록 오류: {exc}", file=sys.stderr)
        return 2
    try:
        results = seed_documents(
            items, db.get_documents(), replace=args.replace, on_result=_print
        )
    except db.DatabaseUnavailableError as exc:
        print(f"DB 연결 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    finally:
        close_rag_resources()
    failed = sum(r.action == "failed" for r in results)
    done = sum(r.action in ("added", "reindexed", "replaced") for r in results)
    print(f"임베딩 {done}건, 건너뜀 {len(results) - done - failed}건, 실패 {failed}건")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
