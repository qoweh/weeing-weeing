"""코드와 무관하게 후보 지속·등급 유지·회복 및 Manager 연결을 처리한다."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from weeing_weeing.contracts import Incident, Severity, TelemetryRecord
from weeing_weeing.contracts.codes import CODES
from weeing_weeing.detector.builtin_rules import BuiltinRules, default_policies
from weeing_weeing.detector.incident_manager import IncidentManager
from weeing_weeing.detector.rule_models import RuleAssessment, RuleDecision, RulePolicy


@dataclass
class _RuleState:
    warning_since: datetime | None = None
    error_since: datetime | None = None
    normal_since: datetime | None = None
    candidate_key: tuple[str | None, str] | None = None
    severity: Severity | None = None
    first_detected_at: datetime | None = None
    recovered_at: datetime | None = None

    def interrupt(self) -> None:
        self.warning_since = self.error_since = self.normal_since = None
        self.candidate_key = None


class RuleEvaluator:
    """모든 CODES를 동일한 상태 전이로 처리한다.

    기본 제공 룰 대신 assessments를 전달하면 별도의 룰 구현도 같은 경로를
    사용한다. 전달하지 않은 룰은 Unknown이며 회복시키지 않는다.
    """

    def __init__(
        self,
        *,
        enabled_codes: set[str] | None = None,
        policies: dict[str, RulePolicy] | None = None,
    ) -> None:
        self.enabled_codes = set(CODES) if enabled_codes is None else set(enabled_codes)
        self.policies = default_policies()
        self.policies.update(policies or {})
        if (self.enabled_codes | self.policies.keys()) - CODES.keys():
            raise ValueError("정의되지 않은 룰 코드")
        self._previous: dict[tuple[str, str], TelemetryRecord] = {}
        self._context_keys: dict[tuple[str, str], tuple[object, ...]] = {}
        self._states: dict[tuple[str, str, str], _RuleState] = {}
        self._rules = BuiltinRules()
        self.last_assessments: list[RuleAssessment] = []

    def _interrupt(self, key: tuple[str, str]) -> None:
        self._rules.reset(key)
        for (*asset, _code), state in self._states.items():
            if tuple(asset) == key:
                state.interrupt()

    def evaluate(
        self,
        record: TelemetryRecord,
        plc_context: dict[str, Any] | None = None,
        *,
        assessments: list[RuleAssessment] | None = None,
    ) -> list[RuleDecision]:
        context = plc_context or {}
        key = record.process_id, record.asset_id
        previous = self._previous.get(key)
        gap = False
        if previous is not None:
            if record == previous:
                self.last_assessments = []
                return []
            if (
                record.record_id == previous.record_id
                or record.timestamp <= previous.timestamp
            ):
                self._interrupt(key)
                raise ValueError("레코드 ID 충돌 또는 증가하지 않는 timestamp")
            gap = (record.timestamp - previous.timestamp).total_seconds() > 2
            if gap:
                self._interrupt(key)
        supplied = assessments
        if supplied is not None:
            codes = [item.rule_code for item in supplied]
            if len(codes) != len(set(codes)):
                raise ValueError("한 레코드에 같은 룰 평가가 중복됨")
            if any(
                item.started_at and item.started_at > record.timestamp
                for item in supplied
            ):
                raise ValueError("후보 시작은 판정 시각보다 늦을 수 없음")
        baseline = context.get("vibration_baseline")
        context_key = tuple(
            context.get(name)
            for name in (
                "run_cmd",
                "planned_hold",
                "maintenance_mode",
                "recipe_id",
                "config_version",
                "run_started_at",
                "fixed_speed",
                "same_load",
                "vibration_comparable",
            )
        ) + (baseline.get("version") if isinstance(baseline, dict) else None,)
        if key in self._context_keys and self._context_keys[key] != context_key:
            self._interrupt(key)
        self._context_keys[key] = context_key
        self._previous[key] = record
        if context.get("telemetry_valid", True) is not True:
            self._interrupt(key)
            supplied = [
                RuleAssessment(code, Severity.UNKNOWN, reason="입력 품질 무효")
                for code in self.enabled_codes
            ]
        elif supplied is None:
            supplied = self._rules.evaluate(record, context, gap=gap)
        by_code = {item.rule_code: item for item in supplied}
        self.last_assessments = [
            by_code.get(
                code,
                RuleAssessment(code, Severity.UNKNOWN, reason="룰 평가 결과 미제공"),
            )
            for code in sorted(self.enabled_codes)
        ]
        decisions = []
        for item in self.last_assessments:
            state = self._states.setdefault((*key, item.rule_code), _RuleState())
            decision = self._advance(record, item, state)
            if decision is not None:
                decisions.append(decision)
        return decisions

    def _advance(
        self, record: TelemetryRecord, item: RuleAssessment, state: _RuleState
    ) -> RuleDecision | None:
        at = record.timestamp
        policy = self.policies[item.rule_code]
        if item.severity in (Severity.UNKNOWN, Severity.SUPPRESSED):
            state.interrupt()
            return None
        if item.severity == Severity.NORMAL:
            state.warning_since = state.error_since = None
            state.candidate_key = None
            if state.severity is None:
                return None
            if state.normal_since is None:
                state.normal_since = at
            if (at - state.normal_since).total_seconds() < policy.recovery_s:
                return None
            assert state.first_detected_at is not None
            decision = RuleDecision(
                record,
                item.rule_code,
                "recover",
                state.severity,
                state.first_detected_at,
                item.evidence,
                item.direction,
            )
            state.severity = state.first_detected_at = None
            state.recovered_at = at
            state.interrupt()
            return decision
        state.normal_since = None
        signature = item.direction, item.candidate_key
        if state.candidate_key != signature:
            state.warning_since = state.error_since = None
            state.candidate_key = signature
        if state.warning_since is None:
            state.warning_since = at
        if item.severity == Severity.ERROR:
            if state.error_since is None:
                state.error_since = at
        else:
            state.error_since = None
        confirmed = None
        if (
            state.error_since is not None
            and (at - state.error_since).total_seconds() >= policy.error_s
        ):
            confirmed = Severity.ERROR
        elif (at - state.warning_since).total_seconds() >= policy.warning_s:
            confirmed = Severity.WARNING
        if confirmed is None:
            return None
        action = "confirm" if state.severity is None else "update"
        if state.severity is None:
            state.first_detected_at = item.started_at or state.warning_since
            if (
                state.recovered_at is not None
                and state.first_detected_at <= state.recovered_at
            ):
                # 이벤트의 측정 구간이 이전 사건의 회복 시각을 포함할 수 있다.
                # 새 후보는 회복 이후 첫 이상 관측부터 기록한다.
                state.first_detected_at = state.warning_since
        if state.severity != Severity.ERROR:
            state.severity = confirmed
        assert state.first_detected_at is not None
        return RuleDecision(
            record,
            item.rule_code,
            action,
            state.severity,
            state.first_detected_at,
            item.evidence,
            item.direction,
        )


class RuleDetector:
    """범용 Detector 구현. Manager는 판정 결과의 기록만 담당한다."""

    def __init__(
        self,
        *,
        enabled_codes: set[str] | None = None,
        policies: dict[str, RulePolicy] | None = None,
    ) -> None:
        self.evaluator = RuleEvaluator(enabled_codes=enabled_codes, policies=policies)
        self._manager = IncidentManager()

    @property
    def last_assessments(self) -> list[RuleAssessment]:
        return list(self.evaluator.last_assessments)

    def process(
        self, record: TelemetryRecord, plc_context: dict[str, Any] | None = None
    ) -> list[Incident]:
        return self._apply(self.evaluator.evaluate(record, plc_context))

    def process_assessments(
        self, record: TelemetryRecord, assessments: list[RuleAssessment]
    ) -> list[Incident]:
        """별도 룰 평가기도 동일한 확정·Manager 경로로 연결한다."""
        return self._apply(self.evaluator.evaluate(record, assessments=assessments))

    def _apply(self, decisions: list[RuleDecision]) -> list[Incident]:
        changed = []
        for item in decisions:
            if item.action == "recover":
                incident = self._manager.recover(item.record, item.rule_code)
            elif item.action == "confirm":
                incident = self._manager.confirm(
                    item.record,
                    item.rule_code,
                    severity=item.severity,
                    first_detected_at=item.first_detected_at,
                    evidence=item.evidence,
                    direction=item.direction,
                )
            else:
                incident = self._manager.update(
                    item.record,
                    item.rule_code,
                    severity=item.severity,
                    evidence=item.evidence,
                    direction=item.direction,
                )
            changed.append(incident)
        return changed

    def active_incidents(self) -> list[Incident]:
        return self._manager.active_incidents()
