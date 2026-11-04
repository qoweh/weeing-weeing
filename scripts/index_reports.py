"""대기 중인 승인 보고서를 RAG에 등록한다.

--retry-failed  실패한 작업도 다시 시도한다
--all           이미 등록한 최신 승인 판도 다시 등록한다(벡터 컬렉션을 바꾼 뒤). 실패 작업 포함
"""

import argparse

from weeing_weeing.api.report_index import run_pending_reports
from weeing_weeing.db import interface as db
from weeing_weeing.rag.interface import close_rag_resources


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    try:
        if args.all:
            requeued = db.get_reports().requeue_indexed_reports()
            print(f"다시 등록 대기로 바꾼 보고서 {requeued}건")
        result = run_pending_reports(retry_failed=args.retry_failed or args.all)
    finally:
        close_rag_resources()
    print(f"등록 완료 {result.indexed}건, 실패 {result.failed}건")
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
