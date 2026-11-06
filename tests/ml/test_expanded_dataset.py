"""다중 원본·새 클래스·기존 분할 보호·확률 매핑 회귀 검사."""

import csv
from copy import deepcopy

import numpy as np
import pytest

pytest.importorskip("sklearn")

from test_future_error import FakeModel, metadata, rows  # noqa: E402

from weeing_weeing.ml.data import (  # noqa: E402
    COLUMNS,
    load_dataset,
    scenario,
    split_runs,
    validate_manifest,
)
from weeing_weeing.ml.features import CLASSES, classes_for_codes  # noqa: E402
from weeing_weeing.ml.interface import FutureErrorPredictor  # noqa: E402


def source(tmp_path, code, *, filename=None, record_prefix=None, override=None):
    values = rows(73)
    run = f"ml-{code}-fault-0-abcdef-123abc"
    for i, row in enumerate(values):
        row.update(
            record_id=f"{record_prefix or code}-{i}",
            run_id=run,
            process_id="P",
            asset_id="A",
            schema_version="3.0.0",
            target_label=f"BTT2-{code}",
            timestamp=row["timestamp"].isoformat(),
        )
    if override:
        values[0].update(override)
    path = tmp_path / (filename or f"{code}.csv")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(values)
    return path


def test_multiple_csv_sources_new_codes_and_content_hash(tmp_path):
    first, second = source(tmp_path, "M02"), source(tmp_path, "M03")
    groups, audit = load_dataset([first, second])
    reverse_groups, reverse = load_dataset([second, first])
    assert audit["rows"] == 146 and audit["runs"] == 2
    assert audit["classes"] == ["NO_ERROR", "BTT2-M02", "BTT2-M03"]
    assert len(audit["sources"]) == 2
    assert audit["sha256"] == reverse["sha256"]
    assert set(groups) == set(reverse_groups)
    assert scenario("ml-M18-fault-15-abcdef-123abc") == "BTT2-M18"
    with pytest.raises(ValueError):
        scenario("ml-M99-fault-1-abcdef-123abc")
    with pytest.raises(ValueError):
        load_dataset(source(tmp_path, "M03", override={"target_label": "BTT2-M05"}))


def test_cross_file_record_and_run_overlap_rejected(tmp_path):
    first = source(tmp_path, "M02")
    duplicate_ids = source(tmp_path, "M03", record_prefix="M02")
    with pytest.raises(ValueError, match="record_id overlaps"):
        load_dataset([first, duplicate_ids])
    same_run = source(tmp_path, "M02", filename="other.csv", record_prefix="different")
    with pytest.raises(ValueError, match="run_id overlaps"):
        load_dataset([first, same_run])


def run_groups(codes):
    return {f"ml-{c}-fault-{i}-abcdef-123abc": [] for c in codes for i in range(15)}


def test_extend_manifest_preserves_original_runs_and_is_reproducible():
    old = run_groups([c.removeprefix("BTT2-") for c in CLASSES[1:]])
    previous = split_runs(old, "original")
    groups = old | run_groups(["M03", "M18"])
    manifest = split_runs(groups, "combined", previous, ["original", "new"])
    assert manifest == split_runs(
        dict(reversed(list(groups.items()))), "combined", previous, ["new", "original"]
    )
    for split, runs in previous["splits"].items():
        assert set(runs) == set(manifest["splits"][split]) & set(old)
    assert manifest["extended_from"]["preserved_runs"] == 60
    assert [len(manifest["splits"][s]) for s in ("train", "validation", "test")] == [
        54,
        18,
        18,
    ]
    validate_manifest(manifest, groups, "combined")
    with pytest.raises(ValueError, match="source hash"):
        split_runs(groups, "combined", previous, ["wrong"])
    bad = deepcopy(manifest)
    bad["splits"]["test"][0] = bad["splits"]["train"][0]
    with pytest.raises(ValueError, match="overlap"):
        validate_manifest(bad, groups, "combined")


def test_expanded_class_probabilities_save_load_and_metadata_validation(tmp_path):
    import joblib
    from sklearn.ensemble import RandomForestClassifier

    from weeing_weeing.ml.features import FEATURE_NAMES, extract_features

    codes = [f"BTT2-M{i:02}" for i in range(2, 19) if i not in (4, 9)]
    classes = classes_for_codes(codes)
    x = np.array([extract_features(rows(61))[0] + i for i in range(len(classes))])
    model = RandomForestClassifier(n_estimators=3, random_state=7).fit(x, classes)
    meta = metadata() | {
        "classes": model.classes_.tolist(),
        "feature_names": FEATURE_NAMES,
    }
    path = tmp_path / "expanded.joblib"
    joblib.dump({"model": model, "metadata": meta}, path)
    predictor = FutureErrorPredictor.load(path)
    result = predictor.predict(rows(61))
    assert len(result["probabilities"]) == 16
    assert len(result["supported_fault_codes"]) == 15
    assert result["probabilities"] == dict(
        zip(model.classes_, model.predict_proba(x[:1])[0], strict=True)
    )
    assert result["error_probability"] == pytest.approx(
        1 - result["probabilities"]["NO_ERROR"]
    )
    assert len(result["fault_top3"]) == 3
    assert result["fault_top3"] == sorted(
        result["fault_top3"], key=lambda r: (-r["confidence"], r["code"])
    )
    with pytest.raises(ValueError, match="classes"):
        FutureErrorPredictor(model, meta | {"classes": list(reversed(meta["classes"]))})
    # 클래스 메타데이터가 없는 기존 호환 경로는 v1의 5클래스에만 적용한다.
    assert FutureErrorPredictor(FakeModel(), metadata()).predict(rows(61))[
        "input_valid"
    ]
    with pytest.raises(ValueError, match="classes"):
        FutureErrorPredictor(model, metadata())
