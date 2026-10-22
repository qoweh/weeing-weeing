"""모든 룰에 공통인 순간 평가·확정 판정·시간 정책. detector 내부 모델이다."""

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Literal

from weeing_weeing.contracts import SensorEvidence, Severity, TelemetryRecord
from weeing_weeing.contracts.codes import CODES, Direction


@dataclass(frozen=True)
class RulePolicy:
    warning_s: float = 0
    error_s: float = 0
    recovery_s: float = 0

    def __post_init__(self) -> None:
        if any(
            not isfinite(v) or v < 0
            for v in (self.warning_s, self.error_s, self.recovery_s)
        ):
            raise ValueError("지속·회복 시간은 유한한 0 이상 값이어야 함")


@dataclass(frozen=True)
class RuleAssessment:
    """순간 후보 또는 명시적인 정상·판정 불가·억제 결과.

    Normal은 해당 룰의 회복 조건을 평가할 수 있다는 뜻이다. 이벤트 룰은
    정상 이벤트 개수 등 자체 회복 조건까지 충족했을 때만 Normal을 전달한다.
    """

    rule_code: str
    severity: Severity
    evidence: list[SensorEvidence] = field(default_factory=list)
    direction: Direction | None = None
    started_at: datetime | None = None
    reason: str | None = None
    candidate_key: str = ""
    context_missing: bool = False

    def __post_init__(self) -> None:
        if self.rule_code not in CODES:
            raise ValueError(f"정의되지 않은 코드: {self.rule_code}")
        if self.severity not in Severity:
            raise ValueError("유효하지 않은 등급")
        if self.direction not in (None, "L", "H"):
            raise ValueError("유효하지 않은 방향")
        if self.started_at is not None and (
            self.started_at.tzinfo is None or self.started_at.utcoffset() is None
        ):
            raise ValueError("후보 시작 시각에는 시간대가 필요함")


@dataclass(frozen=True)
class RuleDecision:
    record: TelemetryRecord
    rule_code: str
    action: Literal["confirm", "update", "recover"]
    severity: Severity
    first_detected_at: datetime
    evidence: list[SensorEvidence]
    direction: Direction | None = None
