# Incident Manager 기능
# | 기능     | 하는 일 |
# | 사건 찾기 | 설비·룰 코드에 해당하는 진행 중 사건 조회 |
# | 사건 보관 | 생성된 Incident를 메모리에 보관 |
# | 사건 조회 | 전체 사건 또는 진행 중 사건 반환 |


from datetime import datetime
from uuid import uuid4

from weeing_weeing.contracts import (
    Incident,
    IncidentStatus,
    SensorEvidence,
    Severity,
    TelemetryRecord,
)
from weeing_weeing.contracts.codes import Direction

IncidentKey = tuple[str, str, str]


class IncidentManager:
    """룰 평가자가 확정한 발생·지속·회복을 메모리에 기록한다.

    임계값과 회복 대기 시간은 호출자가 판정한다. 초기 정책은 공정·설비·룰별
    한 사건이며, 회복 후 재발은 새 사건으로 기록한다. 반환값은 독립된 사본이다.
    단일 프로세스에서 순차 호출하며, 프로세스가 종료되면 기록은 사라진다.
    """

    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}
        self._active_by_rule: dict[IncidentKey, str] = {}
        self._last_recovered_at: dict[IncidentKey, datetime] = {}

    @staticmethod
    def _key(record: TelemetryRecord, rule_code: str) -> IncidentKey:
        return record.process_id, record.asset_id, rule_code

    def _require_active(self, key: IncidentKey) -> Incident:
        if key not in self._active_by_rule:
            raise KeyError(f"진행 중인 사건이 없음: {key}")
        return self._incidents[self._active_by_rule[key]]

    @staticmethod
    def _check_time(incident: Incident, at: datetime) -> None:
        if at < incident.last_detected_at:
            raise ValueError("사건의 마지막 감지 시각보다 이전 입력은 처리할 수 없음")

    def confirm(
        self,
        record: TelemetryRecord,
        rule_code: str,
        *,
        severity: Severity,
        first_detected_at: datetime | None = None,
        evidence: list[SensorEvidence] | None = None,
        direction: Direction | None = None,
    ) -> Incident:
        """이상 확정 시 생성한다. 같은 사건이 진행 중이면 지속 판정으로 갱신한다.

        record.timestamp는 확정 시각이다. 후보 시작 시각을 생략하면 같은 시각을 쓴다.
        evidence는 호출자가 선택한 센서값·임계값·판정 설명을 그대로 기록한다.
        재발의 후보 시작·확정 시각은 이전 회복 시각보다 늦어야 한다.
        """
        key = self._key(record, rule_code)
        first = first_detected_at if first_detected_at is not None else record.timestamp
        if first.tzinfo is None or first.utcoffset() is None:
            raise ValueError("후보 시작 시각에는 시간대가 필요함")
        if first > record.timestamp:
            raise ValueError("후보 시작 시각은 확정 시각보다 늦을 수 없음")
        recovered_at = self._last_recovered_at.get(key)
        if recovered_at is not None and first <= recovered_at:
            raise ValueError(
                "재발의 후보 시작·확정 시각은 이전 회복 시각보다 늦어야 함"
            )
        if key in self._active_by_rule:
            return self.update(
                record,
                rule_code,
                severity=severity,
                evidence=evidence,
                direction=direction,
            )

        incident = Incident(
            incident_id=f"INC-{uuid4().hex}",
            process_id=record.process_id,
            asset_id=record.asset_id,
            codes=[rule_code],
            severity=severity,
            direction=direction,
            first_detected_at=first,
            confirmed_at=record.timestamp,
            last_detected_at=record.timestamp,
            evidence=evidence if evidence is not None else [],
        ).model_copy(deep=True)
        self._incidents[incident.incident_id] = incident
        self._active_by_rule[key] = incident.incident_id
        return incident.model_copy(deep=True)

    def update(
        self,
        record: TelemetryRecord,
        rule_code: str,
        *,
        severity: Severity | None = None,
        evidence: list[SensorEvidence] | None = None,
        direction: Direction | None = None,
    ) -> Incident:
        """지속 중인 사건의 마지막 감지 시각과 최신 판정 근거를 갱신한다.

        생략한 등급·근거·방향은 유지한다. evidence=[]는 근거를 비운다.
        사건이 없으면 KeyError, 시간 역순 입력이면 ValueError를 발생시킨다.
        """
        incident = self._require_active(self._key(record, rule_code))
        self._check_time(incident, record.timestamp)
        data = incident.model_dump()
        data["last_detected_at"] = record.timestamp
        if severity is not None:
            data["severity"] = severity
        if evidence is not None:
            data["evidence"] = evidence
        if direction is not None:
            data["direction"] = direction
        updated = Incident.model_validate(data).model_copy(deep=True)
        self._incidents[updated.incident_id] = updated
        return updated.model_copy(deep=True)

    def recover(self, record: TelemetryRecord, rule_code: str) -> Incident:
        """호출자가 회복 조건 충족을 판정했을 때 RECOVERED로 바꾼다.

        마지막 이상 감지 시각은 유지하고 회복 시각을 별도로 기록한다.
        보고서 승인에 해당하는 CLOSED 전환은 수행하지 않는다.
        """
        key = self._key(record, rule_code)
        incident = self._require_active(key)
        self._check_time(incident, record.timestamp)
        data = incident.model_dump()
        data.update(status=IncidentStatus.RECOVERED, recovered_at=record.timestamp)
        recovered = Incident.model_validate(data)
        self._incidents[recovered.incident_id] = recovered
        self._last_recovered_at[key] = record.timestamp
        del self._active_by_rule[key]
        return recovered.model_copy(deep=True)

    def find_active(
        self, process_id: str, asset_id: str, rule_code: str
    ) -> Incident | None:
        """같은 룰로 현재 이상이 진행 중인 사건을 찾는다. 회복된 사건은 제외한다."""
        incident_id = self._active_by_rule.get((process_id, asset_id, rule_code))
        if incident_id is None:
            return None
        return self._incidents[incident_id].model_copy(deep=True)

    def all_incidents(self) -> list[Incident]:
        """회복된 사건을 포함한 전체 기록을 생성 순서대로 반환한다."""
        return [incident.model_copy(deep=True) for incident in self._incidents.values()]

    def active_incidents(self) -> list[Incident]:
        """Detector 계약에 따라 CLOSED가 아닌 사건을 반환한다(RECOVERED 포함)."""
        return [
            incident.model_copy(deep=True)
            for incident in self._incidents.values()
            if incident.status != IncidentStatus.CLOSED
        ]
