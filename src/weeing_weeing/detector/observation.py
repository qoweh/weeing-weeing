"""detector 내부에서 센서 판정 결과를 사건 관리 코드로 전달하는 데이터 구조."""

from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    model_validator,
)

from weeing_weeing.contracts import SensorEvidence

CheckName = Literal[
    "numeric_range",
    "transfer_time",
    "infeed_interval",
    "outfeed_missing",
    "infeed_occupancy",
    "outfeed_occupancy",
    "signal_pattern",
]


class AnomalyObservation(BaseModel):
    """검사 하나에서 발견한 이상 하나. 동시 이상은 이 객체의 리스트로 전달한다.

    에러코드·등급·Incident 상태는 후속 처리에서 결정한다.
    시간은 재생 속도나 행 개수가 아니라 TelemetryRecord.timestamp를 기준으로 한다.
    정상·결측·판정 불가는 이 객체로 표현하지 않는다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    process_id: str
    asset_id: str
    record_id: str  # 이상을 판정한 입력 레코드 ID
    detected_at: AwareDatetime

    check_name: CheckName  # 에러코드가 아닌 내부 검사 종류
    fields: list[str] = Field(min_length=1)  # 관련 TelemetryRecord 센서 필드
    description: str = Field(min_length=1)  # 관측한 이상 설명, 특히 신호 패턴의 근거

    # 수치 검사: 센서값. 시간 검사: 경과 시간(초).
    # 신호 패턴처럼 단일 값으로 표현할 수 없으면 None이고 evidence에 근거를 담는다.
    observed_value: FiniteFloat | bool | None = None
    lower_bound: FiniteFloat | None = None
    upper_bound: FiniteFloat | None = None
    unit: str | None = None
    # 경계 포함 여부와 지속시간 등 구체적인 위반 조건을 기록한다.
    criterion: str = Field(min_length=1)

    # 점유 시작, 입구 감지, 직전 투입 등 시간 계산의 기준 시각.
    started_at: AwareDatetime | None = None
    tray_seq: int | None = None  # 여러 트레이가 진행 중일 때 추적 대상을 구분
    evidence: list[SensorEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent_context(self) -> Self:
        if self.started_at is not None and self.started_at > self.detected_at:
            raise ValueError("started_at은 detected_at보다 늦을 수 없음")
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValueError("lower_bound는 upper_bound보다 클 수 없음")
        return self
