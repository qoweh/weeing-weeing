"""센서·사건·자동 분석 등록과 결과·작업 완료를 각각 원자적으로 저장한다."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select, text, update

from weeing_weeing.contracts import AnalysisResult, Incident, IncidentStatus, Severity
from weeing_weeing.db.incidents import SqlIncidents, UnknownIncidentError, _columns
from weeing_weeing.db.models import (
    AnalysisJobRow,
    AnalysisRow,
    DeletedIncidentRow,
    IncidentRow,
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

    def record_frame(self, record, incidents, *, capacity=100):
        """실패하면 전체 롤백. 유료 AI 호출은 이 트랜잭션 밖에서 실행한다."""
        jobs = []
        with self._transaction() as session:
            if self._engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            self._lock_incidents(
                session, [incident.incident_id for incident in incidents]
            )
            session.execute(
                self._insert(TelemetryRow)
                .values(**_values(record))
                .on_conflict_do_nothing(index_elements=KEY)
            )
            for incident in incidents:
                if session.get(DeletedIncidentRow, incident.incident_id) is not None:
                    continue
                values = _columns(incident) | {"updated_at": now()}
                statement = self._insert(IncidentRow).values(
                    incident_id=incident.incident_id, **values
                )
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["incident_id"],
                        set_={name: statement.excluded[name] for name in values},
                        where=IncidentRow.last_detected_at
                        <= statement.excluded.last_detected_at,
                    )
                )
                if incident.severity == Severity.ERROR and incident.status not in (
                    IncidentStatus.RECOVERED,
                    IncidentStatus.CLOSED,
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

    def retry(self, incident_id, request_id, *, capacity=100):
        with self._transaction() as session:
            if self._engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
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
            latest = session.scalar(
                select(AnalysisJobRow)
                .where(AnalysisJobRow.incident_id == incident_id)
                .order_by(
                    AnalysisJobRow.created_at.desc(), AnalysisJobRow.job_id.desc()
                )
            )
            if latest and latest.status in ACTIVE:
                return _job(latest)
            if latest is None or latest.status != "FAILED":
                raise AnalysisConflictError("실패한 작업만 수동 재요청할 수 있습니다")
            # 실패한 원래 입력 스냅샷을 재사용한다. 회복 뒤의 현재 사건과 섞지 않는다.
            return self._enqueue(
                session, Incident.model_validate(latest.snapshot), key, capacity
            )

    def recover_interrupted(self):
        """단일 API 프로세스 시작 시 실행. 유료 호출을 자동 재실행하지 않는다."""
        with self._transaction() as session:
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
            return row.id

    def fail(self, job_id, code):
        with self._transaction() as session:
            session.execute(
                update(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_id == job_id, AnalysisJobRow.status == "RUNNING"
                )
                .values(status="FAILED", error_code=code, updated_at=now())
            )
