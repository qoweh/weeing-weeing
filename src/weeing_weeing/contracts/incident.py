"""Incident(이상 사건) 계약.

출처: 룰베이스 최종 정의서 v2.0 10절 '사건 저장 계약', 노션 '김민우 (정리본)' 예시 JSON.
같은 현상이 이어지면 새 Incident를 만들지 않고 기존 Incident를 갱신한다.
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from weeing_weeing.contracts.codes import CODES, RULE_VERSION, Direction, Severity
from weeing_weeing.contracts.telemetry import TelemetryProvenance


class IncidentStatus(StrEnum):
    """사건 상태. 센서 회복(RECOVERED)과 종결(CLOSED)은 다르다(SOP 초안 원칙)."""

    OPEN = "OPEN"  # 발생·진행 중
    ACKNOWLEDGED = "ACKNOWLEDGED"  # 관제 담당자 접수
    RECOVERED = "RECOVERED"  # 센서값 정상 복귀, 보고서 승인 전
    CLOSED = "CLOSED"  # 보고서 승인 완료


class SensorEvidence(BaseModel):
    """판정 근거가 된 센서값 하나."""

    field: str  # TelemetryRecord 필드명
    value: float | bool | None
    unit: str | None = None
    valid: bool = True  # False면 결측·무효값
    threshold: str | None = None  # 예: "RUN 중 true 연속 3초 이상"
    observed: str | None = None  # 예: "14:00:20~14:00:29 연속 true (10개 표본)"
    note: str | None = None


class Incident(BaseModel):
    incident_id: str  # 내부 연결용 고유 ID
    incident_number: str | None = None  # DB 저장 시 발급되는 사람이 읽는 번호
    process_id: str
    asset_id: str
    codes: list[str] = Field(min_length=1)  # 묶인 원시 코드 전부 보존
    severity: Severity
    direction: Direction | None = None
    status: IncidentStatus = IncidentStatus.OPEN
    first_detected_at: AwareDatetime  # 후보 시작
    confirmed_at: AwareDatetime | None = None  # 지속시간 충족으로 확정
    last_detected_at: AwareDatetime
    recovered_at: AwareDatetime | None = None
    evidence: list[SensorEvidence] = Field(default_factory=list)
    rule_version: str = RULE_VERSION
    config_version: str | None = None
    profile: Literal["DEMO", "PRODUCTION"] = "DEMO"
    tray_seq: int | None = None
    plc_context: dict[str, Any] = Field(default_factory=dict)  # run_cmd, 운전모드 등
    reason: str | None = None  # Unknown·Suppressed 사유
    telemetry_provenance: TelemetryProvenance | None = None

    @field_validator("codes")
    @classmethod
    def _known_codes(cls, codes: list[str]) -> list[str]:
        unknown = [c for c in codes if c not in CODES]
        if unknown:
            raise ValueError(f"정의되지 않은 코드: {unknown}")
        return codes
