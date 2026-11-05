"""Telemetry v3 계약 (공통 데이터 규격 3.0.0, 15컬럼).

출처: 룰베이스 최종 정의서 v2.0 2절, 노션 '길용현' 데이터 규격 표.
"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "3.0.0"


class TelemetryProvenance(BaseModel):
    """송신자가 선언한 표본 출처. 실측 검증이나 인증을 의미하지 않는다."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    origin: Literal["UNKNOWN", "SIMULATION", "REPLAY", "MEASURED"] = "UNKNOWN"
    expected_interval_s: float | None = Field(default=None, gt=0, le=60)


# CSV 컬럼 순서. 수집 모듈과 시뮬레이터가 이 순서로 내보낸다.
COLUMNS: tuple[str, ...] = (
    "record_id",
    "timestamp",
    "process_id",
    "asset_id",
    "schema_version",
    "infeed_present",
    "outfeed_present",
    "rpm",
    "dc_input_current_a",
    "dc_bus_voltage_v",
    "motor_housing_temp_c",
    "de_vibration_rms_g",
    "de_kurtosis",
    "nde_vibration_rms_g",
    "nde_kurtosis",
)


class TelemetryRecord(BaseModel):
    """1초 집계 구간 [timestamp-1초, timestamp) 의 센서값 한 줄.

    빈 값은 0으로 바꾸지 않고 None으로 둔다(정의서 2절). 전류·온도만 비어 있을 수 있다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str
    timestamp: AwareDatetime
    process_id: str
    asset_id: str
    schema_version: str
    infeed_present: bool  # S01 입구 광전센서, 물체 있음 = True
    outfeed_present: bool  # S02 출구 광전센서
    rpm: float  # S03, rpm
    dc_input_current_a: float | None = None  # S04, A. 모터 상전류와 다름
    dc_bus_voltage_v: float  # S04, V
    motor_housing_temp_c: float | None = None  # S05, ℃. 외함 부착 지점
    de_vibration_rms_g: float  # S06 구동측, g
    de_kurtosis: float  # S06, Pearson 첨도(정규분포 = 3)
    nde_vibration_rms_g: float  # S07 반구동측, g
    nde_kurtosis: float  # S07, Pearson 첨도

    @field_validator("dc_input_current_a", "motor_housing_temp_c", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value
