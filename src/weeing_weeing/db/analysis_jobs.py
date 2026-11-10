"""센서·사건·자동 분석 등록과 결과·작업 완료를 각각 원자적으로 저장한다."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select, update

from weeing_weeing.contracts import AnalysisResult, Incident, IncidentStatus, Severity
from weeing_weeing.contracts.analysis_workflow import (
    AnalysisAgentRun,
    AnalysisCheckpoint,
)
from weeing_weeing.db.incidents import SqlIncidents, UnknownIncidentError
from weeing_weeing.db.models import (
    AnalysisAgentRunRow,
    AnalysisCheckpointRow,
    AnalysisJobRow,
    AnalysisRow,
    DeletedIncidentRow,
    IncidentRow,
    ReportRow,
    ReportVersionRow,
    TelemetryRow,
)
from weeing_weeing.db.session import now, utc
from weeing_weeing.db.telemetry import KEY, _values

ACTIVE = ("PENDING", "RUNNING")


class AnalysisConflictError(ValueError):
    pass


def _job(row):
    if row is None:
        return None
    return {
        "job_id": row.job_id,
        "incident_id": row.incident_id,
        "status": row.status,
        "analysis_id": row.analysis_id,
        "error_code": row.error_code,
        "created_at": utc(row.created_at).isoformat(),
        "updated_at": utc(row.updated_at).isoformat(),
    }


class SqlAnalysisJobs(SqlIncidents):
    def _enqueue(self, session, incident, key, capacity):
        existing = session.scalar(
            select(AnalysisJobRow).where(AnalysisJobRow.request_key == key)
        )
        if existing:
            return _job(existing)
        count = session.scalar(
            select(func.count())
            .select_from(AnalysisJobRow)
            .where(AnalysisJobRow.status.in_(ACTIVE))
        )
        job_id = uuid4().hex
        full = count >= capacity
        created_at = now()
        previous_created_at = session.scalar(
            select(func.max(AnalysisJobRow.created_at)).where(
                AnalysisJobRow.incident_id == incident.incident_id
            )
        )
        # 시계 해상도가 낮거나 시간이 되돌아가도 재시도를 이전 작업 뒤에 둔다.
        if previous_created_at is not None:
            created_at = max(
                created_at, utc(previous_created_at) + timedelta(microseconds=1)
            )
        session.execute(
            self._insert(AnalysisJobRow)
            .values(
                job_id=job_id,
                incident_id=incident.incident_id,
                request_key=key,
                status="FAILED" if full else "PENDING",
                snapshot=incident.model_dump(mode="json"),
                analysis_id=None,
                error_code="queue_full" if full else None,
                created_at=created_at,
                updated_at=created_at,
            )
            .on_conflict_do_nothing()
        )
        row = session.scalar(
            select(AnalysisJobRow)
            .where(
                (AnalysisJobRow.request_key == key)
                | (
                    (AnalysisJobRow.incident_id == incident.incident_id)
                    & AnalysisJobRow.status.in_(ACTIVE)
                )
            )
            .order_by(AnalysisJobRow.created_at.desc())
        )
        return _job(row)

    def record_frame(
        self, record, incidents, *, capacity=100, enqueue_analysis=True, provenance=None
    ):
        """센서·사건은 항상 저장하고, 분석 등록은 옵션이다. 실패하면 전체 롤백."""
        jobs = []
        with self._transaction() as session:
            self._sqlite_write_lock(session)
            self._lock_incidents(
                session, [incident.incident_id for incident in incidents]
            )
            session.execute(
                self._insert(TelemetryRow)
                .values(**_values(record, provenance))
                .on_conflict_do_nothing(index_elements=KEY)
            )
            for incident in sorted(
                incidents,
                key=lambda item: (self._number_prefix(item), item.incident_id),
            ):
                if session.get(DeletedIncidentRow, incident.incident_id) is not None:
                    continue
                incident = self._save_in_transaction(session, incident)
                if (
                    enqueue_analysis
                    and incident.severity == Severity.ERROR
                    and incident.status
                    not in (IncidentStatus.RECOVERED, IncidentStatus.CLOSED)
                ):
                    jobs.append(
                        self._enqueue(
                            session, incident, f"auto:{incident.incident_id}", capacity
                        )
                    )
        return jobs

    def latest_job(self, incident_id):
        with self._transaction() as session:
            return _job(
                session.scalar(
                    select(AnalysisJobRow)
                    .where(AnalysisJobRow.incident_id == incident_id)
                    .order_by(
                        AnalysisJobRow.created_at.desc(), AnalysisJobRow.job_id.desc()
                    )
                )
            )

    def save_agent_run(self, job_id, run: AnalysisAgentRun):
        run = AnalysisAgentRun.model_validate(run.model_dump())
        with self._transaction() as session:
            self._save_agent_run(session, job_id, run)

    def _save_agent_run(self, session, job_id, run):
        job = session.get(AnalysisJobRow, job_id)
        if job is None or job.status != "RUNNING":
            raise AnalysisConflictError("실행 중인 분석 작업이 아닙니다")
        existing = session.get(AnalysisAgentRunRow, (job_id, run.role, run.attempt))
        if existing and existing.data["status"] in (
            "COMPLETED",
            "FAILED",
            "SKIPPED",
        ):
            if existing.data == run.model_dump(mode="json"):
                return
            raise AnalysisConflictError("완료된 단계 결과는 덮어쓸 수 없습니다")
        values = dict(
            job_id=job_id,
            role=run.role,
            attempt=run.attempt,
            data=run.model_dump(mode="json"),
            updated_at=now(),
        )
        session.execute(
            self._insert(AnalysisAgentRunRow)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["job_id", "role", "attempt"],
                set_={"data": values["data"], "updated_at": values["updated_at"]},
            )
        )

    def save_progress(self, job_id, run, checkpoint: AnalysisCheckpoint):
        """단계 공개 결과와 재개 입력을 같은 COMMIT으로 보존한다."""
        checkpoint = AnalysisCheckpoint.model_validate(checkpoint.model_dump())
        run = AnalysisAgentRun.model_validate(run.model_dump())
        if run not in checkpoint.runs:
            raise AnalysisConflictError("단계 결과와 체크포인트 불일치")
        with self._transaction() as session:
            job = session.get(AnalysisJobRow, job_id)
            if job is None or checkpoint.incident_id != job.incident_id:
                raise AnalysisConflictError("체크포인트 사건 ID 불일치")
            self._save_agent_run(session, job_id, run)
            values = dict(
                job_id=job_id, data=checkpoint.model_dump(mode="json"), updated_at=now()
            )
            session.execute(
                self._insert(AnalysisCheckpointRow)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["job_id"],
                    set_={"data": values["data"], "updated_at": values["updated_at"]},
                )
            )

    def checkpoint(self, job_id):
        with self._transaction() as session:
            row = session.get(AnalysisCheckpointRow, job_id)
            return AnalysisCheckpoint.model_validate(row.data) if row else None

    @staticmethod
    def _has_approved_report(session, incident_id):
        return (
            session.scalar(
                select(ReportRow.report_id)
                .join(
                    ReportVersionRow, ReportVersionRow.report_id == ReportRow.report_id
                )
                .where(
                    ReportRow.incident_id == incident_id,
                    ReportVersionRow.report_status == "APPROVED",
                )
                .limit(1)
            )
            is not None
        )

    def has_approved_report(self, incident_id):
        with self._transaction() as session:
            return self._has_approved_report(session, incident_id)

    def agent_runs(self, job_id):
        order = {"documents": 0, "reports": 1, "synthesis": 2, "verification": 3}
        with self._transaction() as session:
            rows = session.scalars(
                select(AnalysisAgentRunRow).where(AnalysisAgentRunRow.job_id == job_id)
            )
            runs = [AnalysisAgentRun.model_validate(row.data) for row in rows]
        return sorted(runs, key=lambda run: (run.attempt, order[run.role]))

    def analysis_input(self, result: AnalysisResult) -> Incident | None:
        """저장된 분석과 정확히 일치하는 실행 입력. 최신 재분석과 섞지 않는다."""
        with self._transaction() as session:
            rows = session.execute(
                select(AnalysisJobRow.snapshot, AnalysisRow.data)
                .join(AnalysisRow, AnalysisJobRow.analysis_id == AnalysisRow.id)
                .where(
                    AnalysisJobRow.incident_id == result.incident_id,
                    AnalysisRow.incident_id == result.incident_id,
                    AnalysisRow.generated_at == utc(result.generated_at),
                )
            )
            for snapshot, data in rows:
                if AnalysisResult.model_validate(data) == result:
                    return Incident.model_validate(snapshot)
        return None

    def save_analysis_with_input(
        self, result: AnalysisResult, incident: Incident
    ) -> int:
        """단건 CLI 분석과 입력을 원자 저장한다. 현재 사건·대기 작업은 변경하지 않는다."""
        result = AnalysisResult.model_validate(result.model_dump())
        if result.incident_id != incident.incident_id:
            raise AnalysisConflictError("분석 사건 ID 불일치")
        with self._transaction() as session:
            self._sqlite_write_lock(session)
            self._lock_incidents(session, [incident.incident_id])
            current = session.get(IncidentRow, incident.incident_id)
            if current is None:
                raise UnknownIncidentError(incident.incident_id)
            if (current.process_id, current.asset_id) != (
                incident.process_id,
                incident.asset_id,
            ):
                raise AnalysisConflictError("분석 입력의 공정·설비가 다릅니다")
            active = session.scalar(
                select(AnalysisJobRow.job_id).where(
                    AnalysisJobRow.incident_id == incident.incident_id,
                    AnalysisJobRow.status.in_(ACTIVE),
                )
            )
            if active is not None:
                raise AnalysisConflictError("대기 또는 실행 중인 분석이 있습니다")
            previous = session.scalar(
                select(func.max(AnalysisJobRow.created_at)).where(
                    AnalysisJobRow.incident_id == incident.incident_id
                )
            )
            timestamp = now()
            if previous is not None:
                timestamp = max(timestamp, utc(previous) + timedelta(microseconds=1))
            row = AnalysisRow(
                incident_id=result.incident_id,
                status=result.status,
                model=result.model,
                prompt_version=result.prompt_version,
                generated_at=utc(result.generated_at),
                data=result.model_dump(mode="json"),
            )
            session.add(row)
            session.flush()
            session.add(
                AnalysisJobRow(
                    job_id=uuid4().hex,
                    incident_id=incident.incident_id,
                    request_key=f"cli:{uuid4().hex}",
                    status="FAILED" if result.status == "FAILED" else "COMPLETED",
                    snapshot=incident.model_dump(mode="json"),
                    analysis_id=row.id,
                    error_code="analysis_failed" if result.status == "FAILED" else None,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            return row.id

    def retry(self, incident_id, request_id, *, capacity=100, expected_job_id=None):
        with self._transaction() as session:
            self._sqlite_write_lock(session)
            self._lock_incidents(session, [incident_id])
            row = session.get(IncidentRow, incident_id)
            if row is None:
                raise UnknownIncidentError(incident_id)
            key = f"manual:{incident_id}:{request_id}"
            previous = session.scalar(
                select(AnalysisJobRow).where(AnalysisJobRow.request_key == key)
            )
            if previous:
                return _job(previous)
            if self._has_approved_report(session, incident_id):
                raise AnalysisConflictError(
                    "최종 승인된 보고서가 있는 사건은 분석을 재시도할 수 없습니다"
                )
            latest = session.scalar(
                select(AnalysisJobRow)
                .where(AnalysisJobRow.incident_id == incident_id)
                .order_by(
                    AnalysisJobRow.created_at.desc(), AnalysisJobRow.job_id.desc()
                )
            )
            if expected_job_id is not None and (
                latest is None or latest.job_id != expected_job_id
            ):
                raise AnalysisConflictError(
                    "분석 작업이 변경되었습니다. 결과를 새로고침해 주세요"
                )
            if latest and latest.status in ACTIVE:
                return _job(latest)
            if latest is None or latest.status != "FAILED":
                raise AnalysisConflictError("실패한 작업만 수동 재요청할 수 있습니다")
            # 실패한 원래 입력 스냅샷을 재사용한다. 회복 뒤의 현재 사건과 섞지 않는다.
            job = self._enqueue(
                session, Incident.model_validate(latest.snapshot), key, capacity
            )
            saved = session.get(AnalysisCheckpointRow, latest.job_id)
            if saved:
                checkpoint = AnalysisCheckpoint.model_validate(saved.data)
                # 실패·진행 단계는 새로 실행하며 성공 단계는 원래 호출 통계까지 보존한다.
                checkpoint.runs = [
                    run.model_copy(
                        update={
                            "reused_from_job_id": run.reused_from_job_id
                            or latest.job_id
                        }
                    )
                    for run in checkpoint.runs
                    if run.status == "COMPLETED"
                ]
                session.add(
                    AnalysisCheckpointRow(
                        job_id=job["job_id"],
                        data=checkpoint.model_dump(mode="json"),
                        updated_at=now(),
                    )
                )
                for run in checkpoint.runs:
                    session.add(
                        AnalysisAgentRunRow(
                            job_id=job["job_id"],
                            role=run.role,
                            attempt=run.attempt,
                            data=run.model_dump(mode="json"),
                            updated_at=now(),
                        )
                    )
            return job

    def recover_interrupted(self):
        """단일 API 프로세스 시작 시 실행. 유료 호출을 자동 재실행하지 않는다."""
        with self._transaction() as session:
            job_ids = list(
                session.scalars(
                    select(AnalysisJobRow.job_id).where(
                        AnalysisJobRow.status == "RUNNING"
                    )
                )
            )
            self._close_agent_runs(session, job_ids, "interrupted")
            return session.execute(
                update(AnalysisJobRow)
                .where(AnalysisJobRow.status == "RUNNING")
                .values(status="FAILED", error_code="interrupted", updated_at=now())
            ).rowcount

    def claim(self):
        with self._transaction() as session:
            row = session.scalar(
                select(AnalysisJobRow)
                .where(AnalysisJobRow.status == "PENDING")
                .order_by(AnalysisJobRow.created_at, AnalysisJobRow.job_id)
                .limit(1)
            )
            if row is None:
                return None
            # 재시도 예약 후 보고서가 승인된 경우에도 새 유료 실행을 시작하지 않는다.
            if row.request_key.startswith("manual:") and self._has_approved_report(
                session, row.incident_id
            ):
                row.status, row.error_code, row.updated_at = (
                    "FAILED",
                    "report_approved",
                    now(),
                )
                self._close_agent_runs(session, [row.job_id], "report_approved")
                return None
            claimed = session.execute(
                update(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_id == row.job_id,
                    AnalysisJobRow.status == "PENDING",
                )
                .values(status="RUNNING", updated_at=now())
            )
            if not claimed.rowcount:
                return None
            return row.job_id, Incident.model_validate(row.snapshot)

    def finish(self, job_id, result):
        # save_analysis와 같은 저장 형식을 작업 완료와 한 트랜잭션으로 쓴다.
        result = AnalysisResult.model_validate(result.model_dump())
        with self._transaction() as session:
            job = session.get(AnalysisJobRow, job_id)
            if job is not None and job.analysis_id is not None:
                saved = session.get(AnalysisRow, job.analysis_id)
                if saved is not None and saved.data == result.model_dump(mode="json"):
                    return saved.id
                raise AnalysisConflictError("이미 다른 결과가 저장된 작업입니다")
            if job is None or job.status != "RUNNING":
                raise AnalysisConflictError("실행 중인 작업이 아닙니다")
            if result.incident_id != job.incident_id:
                raise AnalysisConflictError("분석 사건 ID 불일치")
            row = AnalysisRow(
                incident_id=result.incident_id,
                status=result.status,
                model=result.model,
                prompt_version=result.prompt_version,
                generated_at=utc(result.generated_at),
                data=result.model_dump(mode="json"),
            )
            session.add(row)
            session.flush()
            job.analysis_id = row.id
            job.status = "FAILED" if result.status == "FAILED" else "COMPLETED"
            job.error_code = "analysis_failed" if result.status == "FAILED" else None
            job.updated_at = now()
            self._close_agent_runs(
                session, [job_id], job.error_code or "workflow_finished"
            )
            return row.id

    def fail(self, job_id, code):
        with self._transaction() as session:
            self._close_agent_runs(session, [job_id], code)
            session.execute(
                update(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_id == job_id, AnalysisJobRow.status == "RUNNING"
                )
                .values(status="FAILED", error_code=code, updated_at=now())
            )

    @staticmethod
    def _close_agent_runs(session, job_ids, code):
        if not job_ids:
            return
        rows = session.scalars(
            select(AnalysisAgentRunRow).where(AnalysisAgentRunRow.job_id.in_(job_ids))
        )
        for row in rows:
            run = AnalysisAgentRun.model_validate(row.data)
            if run.status in ("PENDING", "RUNNING"):
                run.status = "FAILED" if run.status == "RUNNING" else "SKIPPED"
                run.error_code, run.summary = (
                    code,
                    "상위 분석 작업이 종료되어 실행을 중단했습니다.",
                )
                run.finished_at = now()
                row.data = run.model_dump(mode="json")
                row.updated_at = now()
