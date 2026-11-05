"""사건에 묶인 읽기 전용 센서 도구. DB 접근은 조립자가 주입한다 (#105)."""

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import fmean
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt

from weeing_weeing.agent.runtime import AgentTool, RunMemory, to_json
from weeing_weeing.contracts import Incident, TelemetryRecord
from weeing_weeing.contracts.telemetry import TelemetryProvenance

logger = logging.getLogger("uvicorn.error.analysis")
MAX_ROWS = 512
UNITS = {
    "infeed_present": "bool",
    "outfeed_present": "bool",
    "rpm": "rpm",
    "dc_input_current_a": "A",
    "dc_bus_voltage_v": "V",
    "motor_housing_temp_c": "℃",
    "de_vibration_rms_g": "g",
    "de_kurtosis": "Pearson",
    "nde_vibration_rms_g": "g",
    "nde_kurtosis": "Pearson",
}
SensorField = Literal[
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
]


@dataclass(frozen=True)
class SensorBatch:
    records: list[TelemetryRecord]
    available_through: datetime | None
    sources: dict[datetime, TelemetryProvenance] = field(default_factory=dict)


class SensorReader(Protocol):
    def __call__(
        self, incident: Incident, start: datetime, end: datetime, *, limit: int
    ) -> SensorBatch:
        """[start,end) 조회. 같은 공정·설비의 최신 저장 시각도 반환한다."""
        ...


class WindowQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    before_seconds: int = Field(ge=0, le=120)
    after_seconds: int = Field(ge=0, le=30)
    fields: list[SensorField] = Field(min_length=1, max_length=10)


class SensorClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    window_id: str
    field: SensorField
    statistic: Literal[
        "min",
        "max",
        "mean",
        "first",
        "last",
        "delta",
        "true_count",
        "false_count",
        "valid_count",
        "missing_count",
    ]
    value: StrictBool | StrictInt | StrictFloat


def _quality(rows, batch, start, stop, truncated):
    profiles = [batch.sources.get(row.timestamp, TelemetryProvenance()) for row in rows]
    origins = dict(Counter(profile.origin for profile in profiles))
    periods = {profile.expected_interval_s for profile in profiles}
    period = next(iter(periods)) if len(periods) == 1 else None
    unobserved = []

    def missing(kind, left, right):
        if right > left:
            unobserved.append(
                {
                    "kind": kind,
                    "start": left.isoformat(),
                    "end": right.isoformat(),
                    "duration_s": (right - left).total_seconds(),
                }
            )

    if rows:
        missing("leading", start, rows[0].timestamp)
        missing(
            "trailing_or_truncated" if truncated else "trailing",
            rows[-1].timestamp,
            stop,
        )
        if period is not None:
            for a, b in zip(rows, rows[1:]):
                if (b.timestamp - a.timestamp).total_seconds() > period * 1.5:
                    missing("between_samples", a.timestamp, b.timestamp)
    else:
        missing("entire_window", start, stop)
    notes = [
        "출처는 송신자 선언이며 실측 검증이 아니다. 값이 일정하거나 문서의 시연값과 비슷하다는 이유로 출처·대체값 여부를 추정하지 않는다.",
        "최대 표본 간격은 반환된 표본 사이에만 해당한다. 요청 전체 구간을 연속으로 간주하지 않는다.",
    ]
    if origins:
        notes.append(
            "표본 출처: "
            + ", ".join(f"{origin} {count}개" for origin, count in origins.items())
        )
    if "SIMULATION" in origins:
        notes.append(
            "SIMULATION은 시뮬레이션 값이다. 가상 시나리오의 관측과 실제 장비 원인 진단을 구분한다."
        )
    if "UNKNOWN" in origins or not origins:
        notes.append("출처 미확인 표본은 실측으로 간주하지 않는다.")
    if period is None:
        notes.append(
            "예상 전송 주기가 없거나 혼합되어 고정 0.5초 기준으로 표본 누락을 판정하지 않는다."
        )
    else:
        notes.append(f"송신자가 선언한 예상 전송 주기는 {period:g}초다.")
    for interval in unobserved:
        label = (
            "미반환 구간(표본 상한 영향 가능)"
            if interval["kind"] == "trailing_or_truncated"
            else "표본 미관측 구간"
        )
        notes.append(
            f"{label}: {interval['start']}~{interval['end']} ({interval['duration_s']:.3f}초). 이 구간의 상태와 원인을 추정하지 않는다."
        )
    return {
        "requested_duration_s": (stop - start).total_seconds(),
        "observed_span_s": (rows[-1].timestamp - rows[0].timestamp).total_seconds()
        if rows
        else 0,
        "leading_unobserved_s": (rows[0].timestamp - start).total_seconds()
        if rows
        else (stop - start).total_seconds(),
        "trailing_unobserved_s": (stop - rows[-1].timestamp).total_seconds()
        if rows
        else 0,
        "max_gap_scope": "returned_samples_only",
        "origins": origins,
        "provenance_basis": "sender_declared_or_unknown",
        "expected_interval_s": period,
        "unobserved_intervals": unobserved,
    }, notes


def window_tool(incident: Incident, reader: SensorReader) -> AgentTool:
    def handler(data, memory: RunMemory):
        query = WindowQuery.model_validate(data)
        start = incident.last_detected_at - timedelta(seconds=query.before_seconds)
        stop = incident.last_detected_at + timedelta(seconds=query.after_seconds)
        # DB는 반열린 구간. after=0에서도 사건 시각의 표본을 포함한다.
        batch = reader(
            incident, start, stop + timedelta(microseconds=1), limit=MAX_ROWS + 1
        )
        rows = sorted(batch.records, key=lambda r: r.timestamp)
        # 잘못 주입된 조회 구현이 다른 설비·구간을 섞으면 분석 자체를 실패시킨다.
        if any(
            r.asset_id != incident.asset_id
            or r.process_id != incident.process_id
            or not start <= r.timestamp <= stop
            for r in rows
        ):
            raise RuntimeError("센서 조회 범위 불일치")
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        gaps = [
            (b.timestamp - a.timestamp).total_seconds() for a, b in zip(rows, rows[1:])
        ]
        notes = ["통계는 저장된 표본 기준이며 물리적 연속 상태·원인을 확정하지 않는다."]
        if not rows:
            notes.append("조회 구간에 저장된 표본이 없다. 정상으로 판단할 수 없다.")
        if batch.available_through is None or batch.available_through < stop:
            notes.append(
                "요청 종료 시각까지 데이터가 수집되지 않았다. 미래 표본을 기다리지 않았다."
            )
        if rows and rows[0].timestamp > start:
            notes.append("요청 시작 시각의 표본이 없다.")
        if rows and rows[-1].timestamp < stop:
            notes.append("요청 종료 시각의 표본이 없다.")
        quality, quality_notes = _quality(rows, batch, start, stop, truncated)
        notes.extend(quality_notes)
        if truncated:
            notes.append("표본 상한으로 일부만 집계했다. 더 좁은 구간을 조회해야 한다.")
        fields = {}
        for name in dict.fromkeys(query.fields):
            valid = [
                (r.timestamp, getattr(r, name))
                for r in rows
                if getattr(r, name) is not None and math.isfinite(getattr(r, name))
            ]
            values = [v for _, v in valid]
            stats = {"valid_count": len(valid), "missing_count": len(rows) - len(valid)}
            if stats["missing_count"]:
                notes.append(
                    f"{name}: 결측·비유한 표본 {stats['missing_count']}개를 통계에서 제외했다."
                )
            if values:
                stats.update(first=values[0], last=values[-1])
                if name.endswith("_present"):
                    stats.update(
                        true_count=sum(values), false_count=len(values) - sum(values)
                    )
                else:
                    stats.update(
                        min=min(values),
                        max=max(values),
                        mean=fmean(values),
                        delta=values[-1] - values[0],
                    )
            changes = [
                {
                    "at": t.isoformat(),
                    "value": v,
                    "gap_seconds": (t - prev_t).total_seconds(),
                }
                for (prev_t, prev), (t, v) in zip(valid, valid[1:])
                if prev != v
            ]
            fields[name] = {
                "unit": UNITS[name],
                "statistics": stats,
                "changes": changes[:16],
                "changes_truncated": len(changes) > 16,
            }
        window_id = f"window-{len(memory.sensor_windows) + 1}"
        summary = {
            "window_id": window_id,
            "incident_id": incident.incident_id,
            "anchor": incident.last_detected_at.isoformat(),
            "start": start.isoformat(),
            "end": stop.isoformat(),
            "available_through": batch.available_through.isoformat()
            if batch.available_through
            else None,
            "first_sample": rows[0].timestamp.isoformat() if rows else None,
            "last_sample": rows[-1].timestamp.isoformat() if rows else None,
            "sample_count": len(rows),
            "truncated": truncated,
            "max_gap_seconds": max(gaps, default=None),
            "quality": quality,
            "notes": notes,
            "fields": fields,
        }
        memory.sensor_windows[window_id] = summary
        logger.info(
            "[센서 구간 조회] incident=%s window=%s rows=%s fields=%s 제한=%s",
            incident.incident_id,
            window_id,
            len(rows),
            ",".join(fields),
            " / ".join(notes),
        )
        return to_json(summary)

    return AgentTool(
        name="get_sensor_window",
        description="현재 사건 마지막 감지 시각 기준 앞 0~120초·뒤 0~30초의 선택 센서 통계와 변화 시각을 조회한다. 원시 행은 반환하지 않는다. 미수집·결측·간격 주의사항을 확인한다.",
        input_schema=WindowQuery.model_json_schema(),
        handler=handler,
    )


def verified_facts(claims: list[SensorClaim], memory: RunMemory) -> list[str]:
    """현재 실행에서 실제 반환한 통계와 대조한 뒤 서버가 관측 문장을 만든다."""
    lines = []
    for claim in claims:
        window = memory.sensor_windows.get(claim.window_id)
        field = window and window["fields"].get(claim.field)
        stats = field["statistics"] if field else {}
        if claim.statistic not in stats:
            logger.info(
                "[센서 수치 검증 거절] window=%s field=%s 조회되지 않은 통계",
                claim.window_id,
                claim.field,
            )
            raise ValueError("조회하지 않았거나 결측인 센서 통계를 인용함")
        actual = stats[claim.statistic]
        if isinstance(actual, bool) != isinstance(
            claim.value, bool
        ) or not math.isclose(actual, claim.value, rel_tol=0, abs_tol=1e-6):
            logger.info(
                "[센서 수치 검증 거절] window=%s field=%s statistic=%s 제출=%s 조회=%s",
                claim.window_id,
                claim.field,
                claim.statistic,
                claim.value,
                actual,
            )
            raise ValueError(
                f"센서 수치 불일치: {claim.field}.{claim.statistic}, 조회값={actual}"
            )
        unit = "개" if claim.statistic.endswith("count") else field["unit"]
        lines.append(
            f"[{claim.window_id} 표본 {window['first_sample']}~{window['last_sample']}] "
            f"{claim.field}.{claim.statistic}={actual} {unit}"
        )
    return lines
