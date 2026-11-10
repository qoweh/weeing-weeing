"""누설·구간·분리·온라인/오프라인 일치의 동작 검증. 실제 CSV 없이 실행 가능."""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

pytest.importorskip("sklearn", reason="ML tests require uv sync --group ml")

from weeing_weeing.ml.data import (  # noqa: E402
    build_windows,
    scenario,
    split_runs,
    validate_manifest,
)
from weeing_weeing.ml.features import (  # noqa: E402
    CLASSES,
    FEATURE_NAMES,
    SENSORS,
    InvalidWindowError,
    extract_features,
    sensor_value,
    utc_timestamp,
)
from weeing_weeing.ml.interface import FutureErrorPredictor  # noqa: E402


def rows(count=181):
    start = datetime(2026, 11, 4, tzinfo=timezone.utc)
    result = []
    for i in range(count):
        result.append(
            {
                **dict.fromkeys(SENSORS, 1.0),
                "infeed_present": "true" if i % 2 else "false",
                "outfeed_present": "false",
                "rpm": 1000 + 2 * i * 0.5,
                "timestamp": start + timedelta(seconds=i * 0.5),
                "target_label": "BTT2-M02",
                "run_id": "ml-M02-fault-0-abcdef-123abc",
            }
        )
    return result


def metadata():
    return {
        "feature_names": FEATURE_NAMES,
        "model_version": "test-v1",
        "warning_threshold": 0.5,
    }


class FakeModel:
    # NO_ERROR를 첫/마지막이라고 가정한 구현은 이 테스트를 통과할 수 없다.
    classes_ = np.array(["BTT2-M12", "NO_ERROR", "BTT2-M02", "BTT2-M10", "BTT2-M07"])

    def predict_proba(self, x):
        self.last_x = x.copy()
        return np.tile([0.1, 0.4, 0.3, 0.15, 0.05], (len(x), 1))


def test_boolean_and_utc():
    assert sensor_value("infeed_present", "false") == 0
    assert sensor_value("infeed_present", "TRUE") == 1
    with pytest.raises(ValueError):
        sensor_value("infeed_present", "0")
    assert utc_timestamp("2026-11-04T09:00:00+09:00").hour == 0
    with pytest.raises(ValueError):
        utc_timestamp("2026-11-04T09:00:00")


def test_time_boundary_and_no_future_or_management_leakage():
    data = rows()
    anchor = data[60]["timestamp"]
    expected, quality = extract_features(data[:61], anchor)
    assert len(expected) == 56
    assert quality["sample_count"] == 60
    assert expected[FEATURE_NAMES.index("rpm__slope_per_second")] == pytest.approx(2)
    altered = deepcopy(data)
    altered[0]["rpm"] = -1e9  # 정확히 t-30은 제외
    for r in altered:
        r["run_id"] = "different"
        r["record_id"] = "secret"
        r["target_label"] = "NO_ERROR"
        r["process_id"] = "do-not-use"
    for r in altered[61:]:
        r["rpm"] = 1e12
    actual, _ = extract_features(altered, anchor)
    np.testing.assert_array_equal(actual, expected)


def test_blank_rows_kept_then_endpoint_excluded():
    data = rows(73)
    # 30초 endpoint는 유효하지만 그 직전 이력의 라벨은 모두 빈 값이다.
    for r in data[:60]:
        r["target_label"] = ""
    data[66]["target_label"] = ""  # 33초 endpoint만 제외
    records, summary = build_windows(
        {"ml-M02-fault-0-abcdef-123abc": data}, ["ml-M02-fault-0-abcdef-123abc"]
    )
    first = next(
        r for r in records if r["reference_time"] == data[60]["timestamp"].isoformat()
    )
    expected, _ = extract_features(data[:61])
    np.testing.assert_array_equal(first["features"], expected)
    assert (
        summary["ml-M02-fault-0-abcdef-123abc"]["excluded"]["blank_endpoint_label"] == 1
    )
    assert (
        summary["ml-M02-fault-0-abcdef-123abc"]["excluded"]["insufficient_history"]
        == 10
    )
    assert summary["ml-M02-fault-0-abcdef-123abc"]["candidates"] == summary[
        "ml-M02-fault-0-abcdef-123abc"
    ]["windows"] + sum(summary["ml-M02-fault-0-abcdef-123abc"]["excluded"].values())


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("short", "insufficient_history"),
        ("gap", "gap_over_1_5s"),
        ("duplicate", "timestamp_order"),
        ("reverse", "timestamp_order"),
        ("nan", "nonfinite_sensor"),
        ("boolean", "invalid_sensor"),
        ("mixed", "mixed_runs"),
        ("sparse", "sample_count"),
    ],
)
def test_invalid_windows(mutation, reason):
    data = rows(61)
    if mutation == "short":
        data = data[1:]
    if mutation == "gap":
        del data[28:31]
    if mutation == "duplicate":
        data[30]["timestamp"] = data[29]["timestamp"]
    if mutation == "reverse":
        data[29], data[30] = data[30], data[29]
    if mutation == "nan":
        data[30]["rpm"] = "NaN"
    if mutation == "boolean":
        data[30]["infeed_present"] = "unknown"
    if mutation == "mixed":
        data[30]["run_id"] = "two"
    if mutation == "sparse":
        data = rows(55)
        for i, r in enumerate(data):
            r["timestamp"] = data[0]["timestamp"] + timedelta(seconds=i * 0.56)
    with pytest.raises(InvalidWindowError, match=reason):
        extract_features(data)


def test_stride_uses_time_and_rejects_original_order():
    data = rows()
    data[5]["timestamp"] += timedelta(milliseconds=30)
    records, _ = build_windows(
        {"ml-M02-fault-0-abcdef-123abc": data}, ["ml-M02-fault-0-abcdef-123abc"]
    )
    assert records[1]["reference_time"] == data[66]["timestamp"].isoformat()
    with pytest.raises(ValueError, match="No valid"):
        build_windows(
            {"ml-M02-fault-0-abcdef-123abc": data},
            ["ml-M02-fault-0-abcdef-123abc"],
            {"ml-M02-fault-0-abcdef-123abc": "timestamp_order"},
        )


def test_scenario_stratified_disjoint_reproducible_manifest():
    groups = {
        f"ml-{code}-fault-{i}-abcdef-123abc": []
        for code in ["M02", "M07", "M10", "M12"]
        for i in range(15)
    }
    manifest = split_runs(groups, "digest")
    assert manifest == split_runs(dict(reversed(list(groups.items()))), "digest")
    assert [len(manifest["splits"][s]) for s in ["train", "validation", "test"]] == [
        36,
        12,
        12,
    ]
    assert Counter(scenario(r) for r in manifest["splits"]["test"]) == dict.fromkeys(
        CLASSES[1:], 3
    )
    bad = deepcopy(manifest)
    bad["splits"]["test"][0] = bad["splits"]["train"][0]
    with pytest.raises(ValueError, match="overlap"):
        validate_manifest(bad, groups, "digest")
    with pytest.raises(ValueError, match="hash"):
        validate_manifest(manifest, groups, "different")


def test_inference_feature_parity_classes_probabilities_and_readiness():
    model = FakeModel()
    predictor = FutureErrorPredictor(model, metadata())
    data = rows(61)
    expected, _ = extract_features(data)
    output = predictor.predict(data)
    np.testing.assert_array_equal(model.last_x[0], expected)
    assert output["probabilities"]["NO_ERROR"] == 0.4
    assert output["error_probability"] == 0.6
    assert output["fault_top3"] == [
        {"code": "BTT2-M02", "confidence": 0.3},
        {"code": "BTT2-M10", "confidence": 0.15},
        {"code": "BTT2-M12", "confidence": 0.1},
    ]
    assert sum(r["confidence"] for r in output["fault_top3"]) == pytest.approx(0.55)
    invalid = predictor.predict(data[1:])
    assert invalid["status"] == "not_ready"
    assert invalid["probabilities"] is None
    assert predictor.predict([])["input_valid"] is False
    with pytest.raises(ValueError, match="classes"):
        bad_model = FakeModel()
        bad_model.classes_ = np.array(["NO_ERROR"])
        FutureErrorPredictor(bad_model, metadata())


def test_saved_forest_offline_online_feature_and_probability_parity(tmp_path):
    import joblib
    from sklearn.ensemble import RandomForestClassifier

    groups = {}
    for i, label in enumerate(CLASSES):
        run = f"ml-M02-fault-{i}-abcdef-123abc"
        data = rows(73)
        for r in data:
            r["run_id"] = run
            r["target_label"] = label
            r["rpm"] += i * 100
        groups[run] = data
    records, _ = build_windows(groups, list(groups))
    x = np.stack([r["features"] for r in records])
    y = [r["target"] for r in records]
    model = RandomForestClassifier(n_estimators=10, random_state=7).fit(x, y)
    path = tmp_path / "model.joblib"
    joblib.dump({"model": model, "metadata": metadata()}, path)
    predictor = FutureErrorPredictor.load(path)
    for i, record in enumerate(records):
        raw = groups[record["run_id"]][record["start_index"] : record["end_index"]]
        result = predictor.predict(raw)
        expected = dict(
            zip(model.classes_, model.predict_proba(x[i : i + 1])[0], strict=True)
        )
        assert result["probabilities"] == expected
        assert result["reference_time"] == record["reference_time"]


def test_csv_audit_reports_differences_and_rejects_duplicate_ids(tmp_path):
    import csv

    from weeing_weeing.ml.data import COLUMNS, load_dataset

    data = rows(73)
    for i, r in enumerate(data):
        r.update(
            record_id=f"id-{i}",
            process_id="process",
            asset_id="asset",
            schema_version="3.0.0",
        )
        r["timestamp"] = r["timestamp"].isoformat()
    data[4]["rpm"] = "inf"
    path = tmp_path / "fixture.csv"

    def write():
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(data)

    write()
    groups, audit = load_dataset(path)
    assert audit["rows"] == 73
    assert audit["sensor_issues"] == {"rpm:nonfinite": 1}
    assert audit["differences_from_supplied_counts"]["rows"]["actual"] == 73
    assert len(groups) == 1
    data[1]["record_id"] = data[0]["record_id"]
    write()
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset(path)


@pytest.mark.parametrize("missing", [1, 2])
def test_sensor_gaps_up_to_1_5_seconds_are_accepted(missing):
    data = rows(61)
    del data[30 : 30 + missing]
    _, quality = extract_features(data)
    assert quality["max_gap_seconds"] == pytest.approx((missing + 1) * 0.5)


def test_sensor_gap_over_1_5_seconds_is_rejected_until_it_leaves_window():
    data = rows(122)
    del data[30:33]
    with pytest.raises(InvalidWindowError, match="gap_over_1_5s"):
        extract_features(data[:58])
    _, quality = extract_features(data)
    assert quality["max_gap_seconds"] == pytest.approx(0.5)
