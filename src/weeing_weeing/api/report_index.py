"""승인 outbox를 RAG 공개 인터페이스로 소비한다. API 백그라운드·CLI가 공유한다."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from weeing_weeing.db import interface as db
from weeing_weeing.rag import interface as rag

LOG = logging.getLogger(__name__)
_RUN_LOCK = Lock()


@dataclass(frozen=True)
class IndexRunResult:
    indexed: int = 0
    failed: int = 0


def process_pending_reports(
    repo: db.ReportRepository,
    indexer_factory: Callable[[], rag.Indexer],
    *,
    retry_failed: bool = False,
) -> IndexRunResult:
    """대기 작업을 모두 처리한다. 보고서 행 잠금으로 승인·벡터 쓰기 순서를 보장한다."""
    with _RUN_LOCK:
        attempted: set[str] = set()

        def next_batch():
            return repo.pending_index_reports(
                include_failed=retry_failed,
                exclude_report_ids=frozenset(attempted),
            )

        reports = next_batch()
        if not reports:
            return IndexRunResult()
        try:
            indexer = indexer_factory()
        except Exception as exc:
            LOG.error("보고서 색인기 준비 실패: %s", type(exc).__name__)
            failed = 0
            while reports:
                for report in reports:
                    attempted.add(report.report_id)
                    try:
                        repo.record_index_result(
                            report.report_id, report.report_version, success=False
                        )
                    except db.ReportNotFoundError:
                        # 처리 대기 목록을 읽은 뒤 삭제된 보고서다.
                        continue
                    failed += 1
                reports = next_batch()
            return IndexRunResult(failed=failed)

        indexed = failed = 0
        while reports:
            for report in reports:
                attempted.add(report.report_id)
                try:
                    with repo.locked_index_job(
                        report.report_id, include_failed=retry_failed
                    ) as work:
                        if work is None:
                            continue
                        try:
                            if indexer.index_report(work.report) != 1:
                                raise ValueError(
                                    "보고서 색인 결과가 한 청크가 아닙니다."
                                )
                        except Exception as exc:
                            LOG.error(
                                "보고서 색인 실패 %s v%s: %s",
                                work.report.report_id,
                                work.report.report_version,
                                type(exc).__name__,
                            )
                            work.finish(False)
                            failed += 1
                        else:
                            work.finish(True)
                            indexed += 1
                except db.DatabaseUnavailableError as exc:
                    LOG.error("검색 등록 DB 잠금 실패: %s", type(exc).__name__)
                    failed += 1
            reports = next_batch()
        return IndexRunResult(indexed=indexed, failed=failed)


def run_pending_reports(*, retry_failed: bool = False) -> IndexRunResult:
    """실제 설정의 DB·벡터 저장소로 대기 보고서를 처리한다."""
    return process_pending_reports(
        db.get_reports(), rag.get_indexer, retry_failed=retry_failed
    )
