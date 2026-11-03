"""대기 중인 승인 보고서를 RAG에 등록한다. 실패 재시도: --retry-failed."""

import argparse

from weeing_weeing.api.report_index import run_pending_reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    result = run_pending_reports(retry_failed=args.retry_failed)
    print(f"등록 완료 {result.indexed}건, 실패 {result.failed}건")
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
