from typing import Any, Protocol

from weeing_weeing.contracts import Incident, TelemetryRecord
from weeing_weeing.detector.history import HistoryConfig as HistoryConfig
from weeing_weeing.detector.history import HistoryDetector as HistoryDetector
from weeing_weeing.detector.history import HistoryError as HistoryError
from weeing_weeing.detector.history import HistoryReader as HistoryReader
from weeing_weeing.detector.p03 import P03Detector as P03Detector
from weeing_weeing.detector.rule_engine import RuleDetector as RuleDetector
from weeing_weeing.detector.rule_models import DetectionFrame as DetectionFrame
from weeing_weeing.detector.rule_models import RuleAssessment as RuleAssessment
from weeing_weeing.detector.rule_models import RulePolicy as RulePolicy


class Detector(Protocol):
    def process(
        self, record: TelemetryRecord, plc_context: dict[str, Any] | None = None
    ) -> list[Incident]:
        """레코드 하나를 평가하고, 이번에 새로 생기거나 상태가 바뀐 Incident만 돌려준다."""
        ...

    def active_incidents(self) -> list[Incident]:
        """아직 CLOSED가 아닌 Incident 전체."""
        ...
