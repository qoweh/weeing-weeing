"""학습·추론 공통 시간 구간 검증과 56개 센서 특징. 미래 센서는 사용하지 않는다."""

from datetime import datetime, timezone

import numpy as np

CLASSES = ["NO_ERROR", "BTT2-M02", "BTT2-M07", "BTT2-M10", "BTT2-M12"]
BOOL_SENSORS = ["infeed_present", "outfeed_present"]
CONTINUOUS = [
    "rpm",
    "dc_input_current_a",
    "dc_bus_voltage_v",
    "motor_housing_temp_c",
    "de_vibration_rms_g",
    "de_kurtosis",
    "nde_vibration_rms_g",
    "nde_kurtosis",
]
SENSORS = BOOL_SENSORS + CONTINUOUS
STATS = ["current", "mean", "min", "max", "std", "slope_per_second"]
BOOL_STATS = ["current", "true_ratio", "rising_count", "falling_count"]
FEATURE_NAMES = [f"{c}__{s}" for c in CONTINUOUS for s in STATS] + [
    f"{c}__{s}" for c in BOOL_SENSORS for s in BOOL_STATS
]
WINDOW_RULES = {
    "seconds": 30,
    "interval": "(t-30s,t]",
    "stride_seconds": 3,
    "min_samples": 55,
    "max_samples": 65,
    "min_observed_seconds": 29.2,
    "max_gap_seconds": 0.8,
    "require_history_at_or_before_left_boundary": True,
    "timestamp_order": "strictly increasing, timezone-aware UTC",
}


class InvalidWindowError(ValueError):
    """reason은 제외 집계와 추론 준비 상태에 공통으로 쓰는 안정적인 코드다."""


def utc_timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


def sensor_value(name, value):
    if name in BOOL_SENSORS:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return float(value.strip().lower() == "true")
        raise ValueError(f"invalid boolean: {name}")
    return float(value)


def extract_features(rows, as_of=None):
    """반환: (특징 ndarray, 품질 정보). 입력 순서를 보존하며 t 이후 행은 무시한다.

    30초 버퍼에는 왼쪽 경계 이전/동일 표본 한 개도 보관해야 한다.
    이 표본은 이력 확보·경계 공백 검증 전용이며 특징에는 포함하지 않는다.
    run_id가 있으면 단일 실행인지 확인한다. 스트림 호출자는 설비/실행별 버퍼를 유지한다.
    """
    if not rows:
        raise InvalidWindowError("insufficient_history")
    try:
        times = np.array([utc_timestamp(r["timestamp"]).timestamp() for r in rows])
        anchor = (
            utc_timestamp(as_of)
            if as_of is not None
            else utc_timestamp(rows[-1]["timestamp"])
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise InvalidWindowError("invalid_timestamp") from exc
    end = anchor.timestamp()
    past = times <= end
    times = times[past]
    rows = [r for r, keep in zip(rows, past, strict=True) if keep]
    if not len(times):
        raise InvalidWindowError("insufficient_history")
    if len({r.get("run_id") for r in rows}) > 1:
        raise InvalidWindowError("mixed_runs")
    if np.any(np.diff(times) <= 0):
        raise InvalidWindowError("timestamp_order")
    left = end - WINDOW_RULES["seconds"]
    if times[0] > left:
        raise InvalidWindowError("insufficient_history")
    selected = times > left
    indexes = np.flatnonzero(selected)
    if not len(indexes):
        raise InvalidWindowError("sample_count")
    start = indexes[0]
    t = times[selected]
    if end - t[-1] > 1e-6:
        raise InvalidWindowError("anchor_not_sample")
    # 경계 직전 표본과 첫 입력 사이도 검사한다. 오래된 이력의 공백은 무관하다.
    if np.max(np.diff(times[max(0, start - 1) :]), initial=0) > 0.800001:
        raise InvalidWindowError("gap_over_0_8s")
    if not WINDOW_RULES["min_samples"] <= len(t) <= WINDOW_RULES["max_samples"]:
        raise InvalidWindowError("sample_count")
    duration = float(t[-1] - t[0])
    if duration < WINDOW_RULES["min_observed_seconds"]:
        raise InvalidWindowError("observed_span")
    window = rows[start:]
    try:
        values = np.array([[sensor_value(c, r[c]) for c in SENSORS] for r in window])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise InvalidWindowError("invalid_sensor") from exc
    if not np.isfinite(values).all():
        raise InvalidWindowError("nonfinite_sensor")
    relative = t - t[0]
    centered = relative - relative.mean()
    features = []
    for j, _ in enumerate(CONTINUOUS, start=2):
        v = values[:, j]
        slope = np.dot(centered, v - v.mean()) / np.dot(centered, centered)
        features.extend([v[-1], v.mean(), v.min(), v.max(), v.std(ddof=0), slope])
    for j, _ in enumerate(BOOL_SENSORS):
        v = values[:, j]
        changes = np.diff(v)
        features.extend([v[-1], v.mean(), (changes > 0).sum(), (changes < 0).sum()])
    result = np.asarray(features, dtype=float)
    if not np.isfinite(result).all():
        raise InvalidWindowError("nonfinite_feature")
    return result, {
        "valid": True,
        "reference_time": anchor.isoformat(),
        "interval_start_exclusive": datetime.fromtimestamp(
            left, timezone.utc
        ).isoformat(),
        "sample_count": len(t),
        "observed_seconds": duration,
        "max_gap_seconds": float(np.max(np.diff(t))),
    }
