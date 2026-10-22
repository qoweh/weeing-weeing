"""BTT-RULE v2.0 후보 평가. 확정·회복 시간 및 사건 관리는 공통 엔진 책임이다.

필수 문맥은 추측하지 않는다. D 코드는 유효 TelemetryRecord로 확인 가능한
품질 상태만 제공한다. 원시 형식 오류·LIVE watchdog은 외부 평가 입력을 사용한다.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from statistics import median
from typing import Any

from weeing_weeing.contracts import (
    SCHEMA_VERSION,
    SensorEvidence,
    Severity,
    TelemetryRecord,
)
from weeing_weeing.contracts.codes import CODES
from weeing_weeing.detector.rule_models import RuleAssessment, RulePolicy

# 필드, A하한, A상한, B, C, 하한 코드, 상한 코드, 단위, 지속시간
NUMERIC_RULES = (
    ("rpm", 1000, 1030, 990, 1040, "M02", "M03", "rpm", 3),
    (
        "dc_input_current_a",
        0.089963,
        0.093786,
        0.080967,
        0.103165,
        "M05",
        "M06",
        "A",
        3,
    ),
    ("dc_bus_voltage_v", 20, 25, 18, 27, "M07", "M08", "V", 1),
    ("motor_housing_temp_c", 45, 85, 40, 90, "M09", "M10", "℃", 10),
    (
        "de_vibration_rms_g",
        0.040396,
        0.080601,
        0.036356,
        0.088661,
        "M11",
        "M12",
        "g",
        3,
    ),
    ("de_kurtosis", 3.5511, 7.0661, 2.8836, 7.7727, "M13", "M14", "-", 3),
    (
        "nde_vibration_rms_g",
        0.049179,
        0.062322,
        0.044261,
        0.068554,
        "M15",
        "M16",
        "g",
        3,
    ),
    ("nde_kurtosis", 3.3565, 5.4770, 2.7413, 6.0248, "M17", "M18", "-", 3),
)


def default_policies() -> dict[str, RulePolicy]:
    policies = {code: RulePolicy() for code in CODES}
    for _, _, _, _, _, low, high, _, duration in NUMERIC_RULES:
        for code in (low, high):
            policies[f"BTT2-{code}"] = RulePolicy(duration, duration, 10)
    policies["BTT2-M01"] = RulePolicy(0, 0, 10)
    policies["BTT2-M04"] = RulePolicy(3, 3, 10)
    policies["BTT2-M19"] = RulePolicy(10, 10, 10)
    for code in ("P03", "P04"):
        policies[f"BTT2-{code}"] = RulePolicy(recovery_s=2)
    return policies


def valid(value: object) -> bool:
    return isinstance(value, (int, float)) and isfinite(value)


def run_age(record: TelemetryRecord, context: dict[str, Any]) -> float | None:
    started = context.get("run_started_at")
    if isinstance(started, str):
        try:
            started = datetime.fromisoformat(started)
        except ValueError:
            return None
    if (
        not isinstance(started, datetime)
        or started.tzinfo is None
        or started.utcoffset() is None
    ):
        return None
    age = (record.timestamp - started).total_seconds()
    return age if age >= 0 else None


@dataclass
class _History:
    previous: TelemetryRecord | None = None
    occupied: dict[str, datetime] = field(default_factory=dict)
    last_in: datetime | None = None
    last_out: datetime | None = None
    pending: deque[datetime] = field(default_factory=deque)
    tracking: bool = False
    expired: bool = False
    intervals: deque[bool] = field(default_factory=lambda: deque(maxlen=5))
    normal_intervals: int = 0
    transfers: deque[tuple[datetime, float]] = field(default_factory=deque)
    normal_transfers: int = 0
    trend_window: list[tuple[datetime, float]] = field(default_factory=list)
    trend_bad_windows: int = 0
    trend_good_windows: int = 0
    rpm_window: deque[tuple[datetime, float]] = field(default_factory=deque)
    startup_complete: bool = False
    stopped_since: datetime | None = None
    context_key: tuple[object, ...] | None = None
    invalid_previous: set[str] = field(default_factory=set)

    def clear_transfer_history(self) -> None:
        self.transfers.clear()
        self.normal_transfers = 0
        self.trend_window.clear()
        self.trend_bad_windows = self.trend_good_windows = 0


class BuiltinRules:
    def __init__(self) -> None:
        self._history: dict[tuple[str, str], _History] = {}

    def reset(self, key: tuple[str, str]) -> None:
        self._history.pop(key, None)

    def evaluate(
        self, record: TelemetryRecord, context: dict[str, Any], *, gap: bool = False
    ) -> list[RuleAssessment]:
        key = record.process_id, record.asset_id
        if key not in self._history:
            self._history[key] = _History()
        state = self._history[key]
        results = {
            code: RuleAssessment(
                code, Severity.UNKNOWN, reason="필수 입력·문맥 또는 이벤트 미확보"
            )
            for code in CODES
        }

        def put(
            code: str,
            severity: Severity,
            fields: tuple[str, ...] = (),
            *,
            criterion: str = "",
            observed: str = "",
            **kwargs: Any,
        ) -> None:
            full_code = f"BTT2-{code}"
            evidence = [
                SensorEvidence(
                    field=name,
                    value=getattr(record, name),
                    threshold=criterion,
                    observed=observed,
                    valid=valid(getattr(record, name)),
                )
                for name in fields
            ]
            if not evidence and kwargs.get("reason"):
                evidence = [
                    SensorEvidence(
                        field="telemetry_quality",
                        value=None,
                        valid=False,
                        observed=kwargs["reason"],
                    )
                ]
            results[full_code] = RuleAssessment(
                full_code, severity, evidence=evidence, **kwargs
            )

        invalid_fields = set(context.get("invalid_fields", ()))
        missing = [
            name
            for name, *_ in NUMERIC_RULES
            if not valid(getattr(record, name)) or name in invalid_fields
        ]
        missing += list(invalid_fields & {"infeed_present", "outfeed_present"})
        put(
            "D01",
            Severity.NORMAL
            if record.schema_version == SCHEMA_VERSION
            else Severity.WARNING,
            reason="스키마 확인"
            if record.schema_version == SCHEMA_VERSION
            else "미지원 스키마",
        )
        put(
            "D02",
            Severity.WARNING if missing else Severity.NORMAL,
            reason=f"무효 센서: {missing}",
        )
        put(
            "D03",
            Severity.WARNING if gap else Severity.NORMAL,
            reason="표본 간격 >2초" if gap else "시간 순서 유효",
        )
        if record.schema_version != SCHEMA_VERSION:
            for code in CODES:
                if not code.startswith("BTT2-D"):
                    results[code] = RuleAssessment(
                        code, Severity.UNKNOWN, reason="미지원 스키마"
                    )
            self.reset(key)
            return list(results.values())
        age = run_age(record, context)
        suppressed = (
            context.get("planned_hold") is True
            or context.get("maintenance_mode") is True
        )
        running = context.get("run_cmd") is True and not suppressed
        # 레시피·비교 조건 변경은 시간창과 추적 연속성을 끊는다.
        context_key = (
            context.get("run_cmd"),
            context.get("planned_hold"),
            context.get("maintenance_mode"),
            context.get("recipe_id"),
            context.get("config_version"),
            context.get("run_started_at"),
            context.get("fixed_speed"),
            context.get("same_load"),
            context.get("vibration_comparable"),
            context.get("events_reliable"),
            context.get("continuous_infeed"),
        )
        if state.context_key is not None and state.context_key != context_key:
            state = self._history[key] = _History()
        state.context_key = context_key
        for (
            name,
            lower,
            upper,
            error_low,
            error_high,
            low,
            high,
            unit,
            _,
        ) in NUMERIC_RULES:
            value = getattr(record, name)
            for code, direction in ((low, "L"), (high, "H")):
                status = Severity.NORMAL
                reason = None
                context_missing = False
                if name in missing:
                    status, reason = Severity.UNKNOWN, "센서 결측·품질 무효"
                elif name == "rpm" and (
                    not running
                    or age is None
                    or age < 3
                    or context.get("fixed_speed") is not True
                ):
                    status, reason = (
                        Severity.UNKNOWN,
                        "RUN·기동 3초·고정 속도 문맥 필요",
                    )
                    context_missing = True
                elif name == "dc_input_current_a" and (
                    not running
                    or age is None
                    or age < 3
                    or context.get("same_load") is not True
                    or context.get("fixed_speed") is not True
                ):
                    status, reason = (
                        Severity.UNKNOWN,
                        "기동 3초·동일 속도/하중 문맥 필요",
                    )
                    context_missing = True
                elif (
                    name == "motor_housing_temp_c"
                    and direction == "L"
                    and (not running or age is None or age < 600)
                ):
                    status, reason = (
                        Severity.UNKNOWN,
                        "저온 평가에는 정상 운전 예열 600초 필요",
                    )
                    context_missing = True
                elif name.startswith(("de_", "nde_")) and (
                    not running or context.get("vibration_comparable") is not True
                ):
                    status, reason = (
                        Severity.UNKNOWN,
                        "동일 속도·하중·특징 추출 조건 확인 필요",
                    )
                    context_missing = True
                elif lower <= value <= upper:
                    status = Severity.NORMAL
                elif (direction == "L" and value < lower) or (
                    direction == "H" and value > upper
                ):
                    status = (
                        Severity.ERROR
                        if value <= error_low or value >= error_high
                        else Severity.WARNING
                    )
                else:
                    # 반대 방향 이탈은 A 정상 회복으로 세지 않는다.
                    status, reason = Severity.UNKNOWN, "반대 방향 이탈: 정상 회복 아님"
                if suppressed and name != "dc_bus_voltage_v":
                    status, reason = Severity.SUPPRESSED, "계획 대기·정비"
                put(
                    code,
                    status,
                    (name,),
                    criterion=f"A=[{lower}, {upper}], B<={error_low}, C>={error_high} {unit}",
                    direction=direction,
                    reason=reason,
                    context_missing=context_missing,
                )
                if valid(value):
                    results[f"BTT2-{code}"].evidence[0].unit = unit

        self._motor(record, context, state, put, age, running, missing)
        self._photoelectric(record, context, state, put, running, invalid_fields)
        self._relative_vibration(record, context, put, running, missing)
        if suppressed:
            for code in CODES:
                if code.startswith("BTT2-P") or (
                    code.startswith("BTT2-M") and code not in ("BTT2-M07", "BTT2-M08")
                ):
                    results[code] = RuleAssessment(
                        code, Severity.SUPPRESSED, reason="계획 대기·정비"
                    )
        unknown = [
            code
            for code, result in results.items()
            if not code.startswith("BTT2-D")
            and result.severity == Severity.UNKNOWN
            and result.context_missing
        ]
        put(
            "D05",
            Severity.WARNING if unknown else Severity.NORMAL,
            reason=f"문맥·설정·이력 미확보: {unknown}",
        )
        state.previous = record
        state.invalid_previous = invalid_fields
        return list(results.values())

    def _motor(self, record, context, state, put, age, running, missing):
        if not running or age is None or "rpm" in missing:
            state.rpm_window.clear()
            state.stopped_since = None
            return
        if record.rpm >= 1000:
            state.startup_complete = True
        if not state.startup_complete and age >= 3:
            put(
                "M01", Severity.ERROR, ("rpm",), criterion="RUN 기동 3초 이후 rpm <1000"
            )
        elif state.startup_complete and record.rpm <= 100:
            if state.stopped_since is None:
                state.stopped_since = record.timestamp
            elapsed = (record.timestamp - state.stopped_since).total_seconds()
            if elapsed >= 3:
                put(
                    "M01",
                    Severity.ERROR,
                    ("rpm",),
                    criterion="기동 완료 후 rpm <=100 연속 3초",
                    started_at=state.stopped_since,
                )
        elif record.rpm >= 1000:
            state.stopped_since = None
            put("M01", Severity.NORMAL)
        else:
            state.stopped_since = None
        if age < 3 or context.get("fixed_speed") is not True:
            state.rpm_window.clear()
            return
        state.rpm_window.append((record.timestamp, record.rpm))
        while (
            state.rpm_window
            and (record.timestamp - state.rpm_window[0][0]).total_seconds() > 20
        ):
            state.rpm_window.popleft()
        samples = list(state.rpm_window)
        if len(samples) != 21 or any(
            (b[0] - a[0]).total_seconds() != 1 for a, b in zip(samples, samples[1:])
        ):
            return
        spread = max(value for _, value in samples) - min(value for _, value in samples)
        put(
            "M04",
            Severity.ERROR
            if spread > 60
            else Severity.WARNING
            if spread > 30
            else Severity.NORMAL,
            ("rpm",),
            criterion="20초 21표본 max-min >30 Warning, >60 Error",
            observed=f"변동폭 {spread:g} rpm",
        )

    def _relative_vibration(self, record, context, put, running, missing):
        put(
            "M19",
            Severity.UNKNOWN,
            reason="승인된 정상 기준·비교 문맥 필요",
            context_missing=True,
        )
        baseline = context.get("vibration_baseline")
        if (
            not running
            or context.get("vibration_comparable") is not True
            or not isinstance(baseline, dict)
            or baseline.get("approved") is not True
            or not baseline.get("version")
        ):
            return
        de, nde = baseline.get("de"), baseline.get("nde")
        if (
            not valid(de)
            or not valid(nde)
            or de <= 0
            or nde <= 0
            or {"de_vibration_rms_g", "nde_vibration_rms_g"} & set(missing)
        ):
            return
        rde, rnde = record.de_vibration_rms_g / de, record.nde_vibration_rms_g / nde
        put("M19", Severity.UNKNOWN, reason="상대 변화 및 정상 회복 조건 미충족")
        if rde <= 1.10 and rnde <= 1.10:
            put("M19", Severity.NORMAL)
        elif (rde > 1.25 and rnde <= 1.10) or (rnde > 1.25 and rde <= 1.10):
            ratio = rde if rde > 1.25 else rnde
            put(
                "M19",
                Severity.ERROR if ratio > 1.50 else Severity.WARNING,
                ("de_vibration_rms_g", "nde_vibration_rms_g"),
                criterion="한쪽 비율 >1.25 Warning, >1.50 Error, 다른 쪽 <=1.10; 10초 지속",
                observed=f"RDE={rde:g}, RNDE={rnde:g}, 기준={baseline['version']}",
                candidate_key="DE" if rde > 1.25 else "NDE",
            )

    def _photoelectric(self, record, context, state, put, running, invalid_fields):
        previous = state.previous
        rising = set()
        for name, code in (("infeed_present", "P03"), ("outfeed_present", "P04")):
            if name in invalid_fields or not running:
                state.occupied.pop(name, None)
                continue
            present = getattr(record, name)
            if present:
                if name not in state.occupied:
                    state.occupied[name] = record.timestamp
                elapsed = (record.timestamp - state.occupied[name]).total_seconds()
                if (
                    previous is not None
                    and name not in state.invalid_previous
                    and getattr(previous, name) is False
                ):
                    rising.add(name)
                if elapsed > 3:
                    put(
                        code,
                        Severity.ERROR if elapsed > 5 else Severity.WARNING,
                        (name,),
                        criterion="연속 true >3초 Warning, >5초 Error; false 2초 회복",
                        observed=f"관측 하한 {elapsed:g}초",
                        started_at=state.occupied[name],
                    )
            else:
                state.occupied.pop(name, None)
                if code == "P03" or context.get("downstream_ready") is True:
                    put(code, Severity.NORMAL)
        if not running or {"infeed_present", "outfeed_present"} & invalid_fields:
            state.tracking = False
            state.pending.clear()
            state.last_in = state.last_out = None
            state.intervals.clear()
            state.clear_transfer_history()
            state.normal_intervals = 0
            return
        if (
            context.get("tracking_reset") is True
            and not record.infeed_present
            and not record.outfeed_present
        ):
            state.pending.clear()
            state.clear_transfer_history()
            state.expired = False
            state.tracking = True
        fields = ("infeed_present", "outfeed_present")
        if context.get("continuous_infeed") is True:
            completed = "infeed_present" in rising
            if state.last_in is not None:
                elapsed = (record.timestamp - state.last_in).total_seconds()
                if completed:
                    bad = not 4 <= elapsed <= 6
                    state.intervals.append(bad)
                    state.normal_intervals = 0 if bad else state.normal_intervals + 1
                    if bad:
                        put(
                            "P05",
                            Severity.ERROR
                            if len(state.intervals) == 5 and sum(state.intervals) >= 3
                            else Severity.WARNING,
                            fields[:1],
                            criterion="투입 4~6초, 최근 5간격 중 3회 이탈 Error",
                            observed=f"간격 {elapsed:g}초",
                            started_at=state.last_in,
                        )
                    elif state.normal_intervals >= 5:
                        put("P05", Severity.NORMAL)
                elif elapsed > 6:
                    put(
                        "P05",
                        Severity.ERROR if elapsed > 10 else Severity.WARNING,
                        fields[:1],
                        criterion="미투입 >6초 Warning, >10초 Error",
                        observed=f"미투입 {elapsed:g}초",
                        started_at=state.last_in,
                    )
        else:
            state.intervals.clear()
            state.normal_intervals = 0
            state.last_in = None
        put(
            "D04",
            Severity.NORMAL
            if state.tracking and context.get("events_reliable") is True
            else Severity.WARNING,
            reason="추적 동기화 확인"
            if state.tracking and context.get("events_reliable") is True
            else "구간 비움·원천 이벤트 신뢰성 미확인",
        )
        if state.tracking and context.get("events_reliable") is True:
            if "outfeed_present" in rising:
                state.last_out = record.timestamp
                if not state.pending:
                    state.tracking = False
                    state.clear_transfer_history()
                    put("D04", Severity.WARNING, reason="대응 입구 없이 출구 감지")
                else:
                    entered = state.pending.popleft()
                    elapsed = (record.timestamp - entered).total_seconds()
                    if state.expired:
                        state.tracking = False
                        state.clear_transfer_history()
                        put(
                            "D04",
                            Severity.WARNING,
                            reason="만료 트레이의 늦은 출구: 재동기화 필요",
                        )
                    else:
                        self._completed_transfer(
                            record, context, state, put, elapsed, entered
                        )
            if "infeed_present" in rising and state.tracking and not state.expired:
                state.pending.append(record.timestamp)
            if state.pending and state.tracking:
                elapsed = (record.timestamp - state.pending[0]).total_seconds()
                if elapsed > 16:
                    state.expired = True
                    put(
                        "P01",
                        Severity.ERROR,
                        fields,
                        criterion="출구 미도착 >16초",
                        observed=f"{elapsed:g}초",
                        started_at=state.pending[0],
                    )
                origin = (
                    max(state.pending[0], state.last_out)
                    if state.last_out
                    else state.pending[0]
                )
                no_out = (record.timestamp - origin).total_seconds()
                if no_out > 16 and context.get("downstream_ready") is True:
                    put(
                        "P06",
                        Severity.ERROR,
                        fields,
                        criterion="RUN·수신 가능·재공 존재·출구 이벤트 없음 >16초",
                        started_at=origin,
                    )
            elif state.tracking and context.get("inspection_confirmed") is True:
                put("P01", Severity.NORMAL)
                put("P06", Severity.NORMAL)
        else:
            state.tracking = False
        if "infeed_present" in rising:
            state.last_in = record.timestamp

    def _completed_transfer(self, record, context, state, put, elapsed, entered):
        state.transfers.append((record.timestamp, elapsed))
        while (
            state.transfers
            and (record.timestamp - state.transfers[0][0]).total_seconds() > 60
        ):
            state.transfers.popleft()
        state.normal_transfers = (
            state.normal_transfers + 1 if 14 <= elapsed <= 16 else 0
        )
        if elapsed < 14:
            recent = list(state.transfers)[-5:]
            put(
                "P02",
                Severity.ERROR
                if len(recent) == 5 and sum(t < 14 for _, t in recent) >= 3
                else Severity.WARNING,
                ("infeed_present", "outfeed_present"),
                criterion="유효 이송 <14초 Warning, 60초 내 최근 5개 중 3회 Error",
                observed=f"FIFO 이송 {elapsed:g}초",
                started_at=entered,
            )
        elif state.normal_transfers >= 5:
            put("P02", Severity.NORMAL)
        if context.get("same_load") is not True or context.get("recipe_id") is None:
            state.trend_window.clear()
            return
        # 60초 내 유효 5개, 서로 겹치지 않는 창만 누적한다.
        state.trend_window.append((record.timestamp, elapsed))
        state.trend_window = [
            (at, t)
            for at, t in state.trend_window
            if (record.timestamp - at).total_seconds() <= 60
        ]
        if len(state.trend_window) < 5:
            return
        values = [t for _, t in state.trend_window]
        state.trend_window.clear()
        bad = median(values) > 15.5 or max(values) - min(values) > 2
        state.trend_bad_windows = state.trend_bad_windows + 1 if bad else 0
        state.trend_good_windows = 0 if bad else state.trend_good_windows + 1
        if bad:
            put(
                "P07",
                Severity.ERROR if state.trend_bad_windows >= 2 else Severity.WARNING,
                ("infeed_present", "outfeed_present"),
                criterion="비중첩 5개 창: median >15.5 또는 max-min >2초",
                observed=f"중앙값 {median(values):g}초, 변동폭 {max(values) - min(values):g}초",
            )
        elif state.trend_good_windows >= 2:
            put("P07", Severity.NORMAL)
