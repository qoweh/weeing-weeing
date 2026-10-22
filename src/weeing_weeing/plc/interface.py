from enum import StrEnum
from typing import Protocol

from weeing_weeing.contracts import TelemetryRecord


class PlcState(StrEnum):
    """초안. 상태 이름과 전환 규칙은 3차 착수 때 SOP와 맞춰 확정한다."""

    STOPPED = "STOPPED"
    IDLE = "IDLE"  # 운전 가능, 투입 대기
    RUNNING = "RUNNING"
    HOLD = "HOLD"  # 신규 투입 보류
    FAULT = "FAULT"  # 보호 정지. 리셋 + 재가동 승인 전까지 기동 금지


class VirtualPlc(Protocol):
    @property
    def state(self) -> PlcState: ...

    def on_telemetry(self, record: TelemetryRecord) -> PlcState:
        """레코드를 반영해 보호 규칙을 평가하고 바뀐 상태를 돌려준다."""
        ...

    def reset(self, by: str) -> None:
        """알람 해제만 한다. 모터는 돌리지 않는다."""
        ...

    def request_start(self, approved_by: str) -> None:
        """재가동 승인자가 명시적으로 요청했을 때만 기동한다."""
        ...
