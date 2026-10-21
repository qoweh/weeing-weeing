from typing import Any, Protocol

from weeing_weeing.contracts import Incident, TelemetryRecord


class Detector(Protocol):
    def process(
        self, record: TelemetryRecord, plc_context: dict[str, Any] | None = None
    ) -> list[Incident]:
        """레코드 하나를 평가하고, 이번에 새로 생기거나 상태가 바뀐 Incident만 돌려준다."""
        ...

    def active_incidents(self) -> list[Incident]:
        """아직 CLOSED가 아닌 Incident 전체."""
        ...
