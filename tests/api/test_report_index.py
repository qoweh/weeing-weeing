"""승인 색인 작업은 한 번 실행할 때 대기 배치를 끝까지 소비한다."""

from contextlib import contextmanager
from types import SimpleNamespace

from weeing_weeing.api.report_index import process_pending_reports


class ManyJobs:
    def __init__(self, count):
        self.reports = {
            f"RPT-{number:03d}": SimpleNamespace(
                report_id=f"RPT-{number:03d}", report_version=1
            )
            for number in range(count)
        }
        self.status = dict.fromkeys(self.reports, "pending")

    def pending_index_reports(
        self, *, limit=100, include_failed=False, exclude_report_ids=frozenset()
    ):
        eligible = {"pending", "failed"} if include_failed else {"pending"}
        return [
            report
            for report_id, report in self.reports.items()
            if report_id not in exclude_report_ids
            and self.status[report_id] in eligible
        ][:limit]

    @contextmanager
    def locked_index_job(self, report_id, *, include_failed=False):
        eligible = {"pending", "failed"} if include_failed else {"pending"}
        if self.status[report_id] not in eligible:
            yield None
            return

        def finish(success):
            self.status[report_id] = "indexed" if success else "failed"

        yield SimpleNamespace(report=self.reports[report_id], finish=finish)

    def record_index_result(self, report_id, version, *, success):
        assert version == 1
        self.status[report_id] = "indexed" if success else "failed"


def test_more_than_one_batch_is_processed_once_each():
    repo = ManyJobs(205)
    indexed = []

    class Indexer:
        def index_report(self, report):
            indexed.append(report.report_id)
            return 1

    result = process_pending_reports(repo, Indexer)
    assert result.indexed == 205 and result.failed == 0
    assert len(indexed) == len(set(indexed)) == 205
    assert set(repo.status.values()) == {"indexed"}


def test_factory_failure_records_each_job_without_retry_loop():
    repo = ManyJobs(105)

    def broken_factory():
        raise RuntimeError("모델 준비 실패")

    result = process_pending_reports(repo, broken_factory, retry_failed=True)
    assert result.indexed == 0 and result.failed == 105
    assert set(repo.status.values()) == {"failed"}
