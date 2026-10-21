from collections.abc import Iterator
from typing import Protocol

from weeing_weeing.contracts import TelemetryRecord


class TelemetrySource(Protocol):
    """Telemetry 공급원. CSV 재생기와 시뮬레이터 수신기가 같은 모양을 따른다."""

    def __iter__(self) -> Iterator[TelemetryRecord]:
        """검증을 통과한 레코드를 시간 순서로 내보낸다.

        형식 오류 행은 버리지 말고 D01로 보고할 수 있게 detector 쪽에 넘길 방법을
        구현 시 정한다(정의서 9절).
        """
        ...
