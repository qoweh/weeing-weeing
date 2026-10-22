"""기존 P03 호출부 호환용 래퍼. 판정·사건 처리는 공통 엔진을 사용한다."""

from weeing_weeing.contracts import TelemetryRecord
from weeing_weeing.detector.rule_engine import RuleDetector, RuleEvaluator
from weeing_weeing.detector.rule_models import RuleDecision

P03Decision = RuleDecision


class P03RuleEvaluator(RuleEvaluator):
    def __init__(self) -> None:
        super().__init__(enabled_codes={"BTT2-P03"})

    def evaluate(
        self,
        record: TelemetryRecord,
        *,
        run_cmd: bool | None = None,
        telemetry_valid: bool = True,
    ) -> list[RuleDecision]:
        return super().evaluate(
            record, {"run_cmd": run_cmd, "telemetry_valid": telemetry_valid}
        )


class P03Detector(RuleDetector):
    def __init__(self) -> None:
        super().__init__(enabled_codes={"BTT2-P03"})
