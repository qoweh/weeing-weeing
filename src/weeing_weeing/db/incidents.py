"""이상 사건(incident)과 AI 분석 결과(analysis) 저장·조회(#61).

계약 전체를 data(JSON)에 넣고 꺼낸다. 칼럼은 목록·필터에 쓰는 값만 뽑은 사본이다.
"""

from datetime import datetime

from sqlalchemy import select, text

from weeing_weeing.contracts import AnalysisResult, Incident, IncidentStatus
from weeing_weeing.db.models import AnalysisRow, DeletedIncidentRow, IncidentRow
from weeing_weeing.db.session import Repository, now, utc


class UnknownIncidentError(LookupError):
    """저장되지 않은 incident_id를 가리켰다(분석 결과는 사건이 먼저 저장돼 있어야 한다)."""


def _columns(incident: Incident) -> dict:
    return {
        "process_id": incident.process_id,
        "asset_id": incident.asset_id,
        "status": incident.status.value,
        "severity": incident.severity.value,
        "codes": list(incident.codes),
        "first_detected_at": utc(incident.first_detected_at),
        "confirmed_at": utc(incident.confirmed_at),
        "last_detected_at": utc(incident.last_detected_at),
        "recovered_at": utc(incident.recovered_at),
        "rule_version": incident.rule_version,
        "data": incident.model_dump(mode="json"),
    }


class SqlIncidents(Repository):
    # --- incident ---

    def save_incident(self, incident: Incident) -> Incident:
        """새 사건은 추가하고, 같은 incident_id면 최신 내용으로 덮어쓴다(갱신·회복).

        한 문장(INSERT … ON CONFLICT DO UPDATE)이라 두 쪽이 동시에 저장해도 충돌하지 않는다.
        저장된 것보다 last_detected_at이 이른 내용은 늦게 도착한 옛 갱신으로 보고 무시한다.
        같은 시각 안의 순서(예: OPEN → RECOVERED)는 호출하는 쪽이 지킨다(detector는 설비별 순차).
        """
        values = _columns(incident) | {"updated_at": now()}
        statement = self._insert(IncidentRow).values(
            incident_id=incident.incident_id, **values
        )
        statement = statement.on_conflict_do_update(
            index_elements=["incident_id"],
            set_={name: statement.excluded[name] for name in values},
            where=IncidentRow.last_detected_at <= statement.excluded.last_detected_at,
        )
        with self._transaction() as session:
            if self._engine.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            self._lock_incidents(session, [incident.incident_id])
            if session.get(DeletedIncidentRow, incident.incident_id) is not None:
                raise UnknownIncidentError("삭제된 사건은 다시 저장할 수 없습니다.")
            session.execute(statement)
        return incident

    def get_incident(self, incident_id: str) -> Incident | None:
        with self._transaction() as session:
            row = session.get(IncidentRow, incident_id)
            return None if row is None else Incident.model_validate(row.data)

    def list_incidents(
        self,
        *,
        asset_id: str | None = None,
        statuses: list[IncidentStatus] | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Incident]:
        """최근 발생순. since는 first_detected_at 기준(포함)."""
        query = select(IncidentRow.data).order_by(
            IncidentRow.first_detected_at.desc(), IncidentRow.incident_id
        )
        if asset_id is not None:
            query = query.where(IncidentRow.asset_id == asset_id)
        if statuses:
            query = query.where(IncidentRow.status.in_([s.value for s in statuses]))
        if since is not None:
            query = query.where(IncidentRow.first_detected_at >= utc(since))
        with self._transaction() as session:
            return [
                Incident.model_validate(data)
                for data in session.scalars(query.limit(limit))
            ]

    # --- analysis ---

    def save_analysis(self, result: AnalysisResult) -> int:
        """분석 결과를 한 건 추가하고 id를 돌려준다. 같은 사건의 이전 결과는 남긴다."""
        with self._transaction() as session:
            if session.get(IncidentRow, result.incident_id) is None:
                raise UnknownIncidentError(result.incident_id)
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
            return row.id

    def latest_analysis(self, incident_id: str) -> AnalysisResult | None:
        analyses = self.list_analyses(incident_id, limit=1)
        return analyses[0] if analyses else None

    def list_analyses(
        self, incident_id: str, *, limit: int = 20
    ) -> list[AnalysisResult]:
        """최근 생성순."""
        query = (
            select(AnalysisRow.data)
            .where(AnalysisRow.incident_id == incident_id)
            .order_by(AnalysisRow.generated_at.desc(), AnalysisRow.id.desc())
            .limit(limit)
        )
        with self._transaction() as session:
            return [AnalysisResult.model_validate(d) for d in session.scalars(query)]
