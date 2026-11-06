"""재현 가능한 오프라인 실험 CLI. 시험 세트는 검증 선택 완료 후 한 번 평가한다."""

import argparse
import csv
import hashlib
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

from .data import SEED, build_windows, load_dataset, split_runs, validate_manifest
from .features import CLASSES, FEATURE_NAMES, WINDOW_RULES, extract_features
from .interface import FutureErrorPredictor
from .probability_metrics import probability_metrics


def write_json(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def matrix(records):
    return np.stack([r["features"] for r in records]), np.array(
        [r["target"] for r in records]
    )


def decisions(model, x, threshold):
    probabilities = model.predict_proba(x)
    normal = list(model.classes_).index("NO_ERROR")
    faults = [i for i, c in enumerate(model.classes_) if c != "NO_ERROR"]
    winner = np.array(faults)[probabilities[:, faults].argmax(axis=1)]
    return np.where(
        1 - probabilities[:, normal] >= threshold, model.classes_[winner], "NO_ERROR"
    )


def metrics(y, predicted, classes=None):
    classes = CLASSES if classes is None else classes
    normal = y == "NO_ERROR"
    return {
        "accuracy": float(accuracy_score(y, predicted)),
        "macro_f1": float(
            f1_score(y, predicted, labels=classes, average="macro", zero_division=0)
        ),
        "classification_report": classification_report(
            y, predicted, labels=classes, output_dict=True, zero_division=0
        ),
        "confusion_matrix": confusion_matrix(y, predicted, labels=classes).tolist(),
        "confusion_matrix_labels": classes,
        "no_error_false_alarm_rate": float(np.mean(predicted[normal] != "NO_ERROR"))
        if normal.any()
        else None,
        "no_error_support": int(normal.sum()),
    }


def evaluate(model, records, threshold, classes=None):
    x, y = matrix(records)
    predicted = decisions(model, x, threshold)
    report = metrics(y, predicted, classes)
    report["probability_metrics"] = probability_metrics(
        y, model.predict_proba(x), model.classes_
    )
    run_ids = np.array([r["run_id"] for r in records])
    report["per_run"] = {
        run: metrics(y[run_ids == run], predicted[run_ids == run], classes)
        for run in sorted(set(run_ids))
    }
    return report, predicted


def balanced_indices(y):
    rng = np.random.default_rng(SEED)
    normal = np.flatnonzero(y == "NO_ERROR")
    faults = np.flatnonzero(y != "NO_ERROR")
    size = min(len(normal), len(faults))
    # 양쪽 중 더 큰 집단만 비복원 축소. 고장 전체는 한 집단으로 취급한다.
    return np.sort(
        np.concatenate(
            [
                rng.choice(normal, size, replace=False),
                rng.choice(faults, size, replace=False),
            ]
        )
    )


def benchmark(predictor, groups, records, repeats=200):
    buffers = []
    for record in records:
        ordered = sorted(groups[record["run_id"]], key=lambda r: r["timestamp"])
        buffers.append(ordered[record["start_index"] : record["end_index"]])
    for rows in buffers[:5]:
        predictor.predict(rows)
    feature_ms, model_ms, total_ms = [], [], []
    for i in range(repeats):
        rows = buffers[i % len(buffers)]
        start = perf_counter()
        features, _ = extract_features(rows)
        middle = perf_counter()
        predictor.model.predict_proba(features.reshape(1, -1))
        end = perf_counter()
        feature_ms.append((middle - start) * 1000)
        model_ms.append((end - middle) * 1000)
        start = perf_counter()
        predictor.predict(rows)
        total_ms.append((perf_counter() - start) * 1000)

    def summary(values):
        return {
            "mean_ms": float(np.mean(values)),
            "p95_ms": float(np.percentile(values, 95)),
            "max_ms": float(max(values)),
        }

    return {
        "repeats": repeats,
        "machine": platform.machine(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": sys.version,
        "feature": summary(feature_ms),
        "predict_proba": summary(model_ms),
        "full_inference": summary(total_ms),
        "observed_under_500ms": max(total_ms) < 500,
        "scope": "current development PC, sequential calls; no real-time scheduling guarantee",
    }


def train(csv_path, output, manifest_path=None, *, extend_manifest_path=None):
    output = Path(output)
    # 기존 모델·시험 결과를 덮어쓰지 않는다. 재실행은 새 출력 폴더를 지정한다.
    output.mkdir(parents=True, exist_ok=False)
    groups, audit = load_dataset(csv_path)
    classes = audit["classes"]
    write_json(output / "data_validation.json", audit)
    manifest = (
        json.loads(Path(manifest_path).read_text())
        if manifest_path
        else split_runs(
            groups,
            audit["sha256"],
            previous_manifest=json.loads(Path(extend_manifest_path).read_text())
            if extend_manifest_path
            else None,
            source_digests=[s["sha256"] for s in audit["sources"]],
        )
    )
    validate_manifest(manifest, groups, audit["sha256"])
    write_json(output / "split_manifest.json", manifest)
    datasets, summaries = {}, {}
    for name, runs in manifest["splits"].items():
        datasets[name], by_run = build_windows(
            groups, runs, audit["timestamp_order_issues"]
        )
        by_code = {}
        for code in classes[1:]:
            selected = [r for r in by_run.values() if r["code"] == code]
            reasons = Counter()
            for r in selected:
                reasons.update(r["excluded"])
            by_code[code] = {
                "runs": len(selected),
                "rows": sum(r["rows"] for r in selected),
                "windows": sum(r["windows"] for r in selected),
                "candidates": sum(r["candidates"] for r in selected),
                "excluded": dict(reasons),
            }
        summaries[name] = {
            "by_run": by_run,
            "by_code": by_code,
            "class_distribution": dict(Counter(r["target"] for r in datasets[name])),
            "raw_class_distribution": dict(
                Counter(r["target_label"] for run in runs for r in groups[run])
            ),
        }
    write_json(output / "window_summary.json", summaries)
    x_train, y_train = matrix(datasets["train"])
    x_val, y_val = matrix(datasets["validation"])
    if set(y_train) != set(classes):
        raise ValueError("All declared training classes required")
    if set(y_val) != set(classes):
        raise ValueError("All declared validation classes required")
    candidates = []
    best = None
    # 사전 고정한 네 가지 모델 + 세 경고 임계값. 시험 지표는 선택에 사용하지 않는다.
    for balanced in (False, True):
        indices = balanced_indices(y_train) if balanced else np.arange(len(y_train))
        if set(y_train[indices]) != set(classes):
            raise ValueError("Training sampling removed a class")
        for leaf in (1, 3):
            model = RandomForestClassifier(
                n_estimators=200, min_samples_leaf=leaf, random_state=SEED, n_jobs=1
            )
            model.fit(x_train[indices], y_train[indices])
            for threshold in (0.3, 0.5, 0.7):
                result = metrics(y_val, decisions(model, x_val, threshold), classes)
                config = {
                    "balanced_normal_fault": balanced,
                    "min_samples_leaf": leaf,
                    "n_estimators": 200,
                    "n_jobs": 1,
                    "threshold": threshold,
                    "fit_class_distribution": dict(Counter(y_train[indices])),
                }
                candidates.append({"configuration": config, "validation": result})
                rank = (result["macro_f1"], -result["no_error_false_alarm_rate"])
                if best is None or rank > best[0]:
                    best = (rank, model, config)
    _, model, chosen = best
    write_json(output / "validation_candidates.json", candidates)
    source_hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path(__file__).parent.glob("*.py")
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "data": audit["sha256"],
                "manifest": manifest,
                "config": chosen,
                "source": source_hashes,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:12]
    version = "rf-future60-v2-" + fingerprint
    metadata = {
        "model_version": version,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": audit["sha256"],
        "source_datasets": [
            {k: s[k] for k in ("source_path", "sha256", "rows", "runs")}
            for s in audit["sources"]
        ],
        "label_schema": classes,
        "seed": SEED,
        "source_sha256": source_hashes,
        "target": "first Error code in (t, t+60s], existing endpoint label, no shift",
        "feature_names": FEATURE_NAMES,
        "classes": model.classes_.tolist(),
        "window_rules": WINDOW_RULES,
        "selected_configuration": chosen,
        "warning_threshold": chosen["threshold"],
        "probability_calibration": "none",
        "preprocessing": "explicit boolean conversion; no scaling, interpolation or imputation",
        "feature_definitions": {
            "continuous": "current, arithmetic mean, min, max, population std (ddof=0), OLS slope using actual seconds",
            "boolean": "current, arithmetic True ratio, adjacent false→true count, adjacent true→false count",
        },
        "selection": "validation Macro F1 maximum, then lower NO_ERROR false alarm rate; deterministic first tie",
        "refit": "train only; validation not merged into training",
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
    }
    write_json(output / "metadata.json", metadata)
    joblib.dump(
        {"model": model, "metadata": metadata}, output / "model.joblib", compress=3
    )
    predictor = FutureErrorPredictor.load(output / "model.joblib")
    results = {}
    for name in ("train", "validation", "test"):
        results[name], predicted = evaluate(
            model, datasets[name], chosen["threshold"], classes
        )
        with (output / f"{name}_predictions.csv").open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "reference_time", "target", "prediction"])
            writer.writerows(
                (r["run_id"], r["reference_time"], r["target"], p)
                for r, p in zip(datasets[name], predicted, strict=True)
            )
        with (output / f"{name}_confusion_matrix.csv").open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["actual/predicted", *classes])
            for label, values in zip(
                classes, results[name]["confusion_matrix"], strict=True
            ):
                writer.writerow([label, *values])
    results["benchmark"] = benchmark(predictor, groups, datasets["test"])
    results["limitations"] = [
        "Overlapping windows are correlated, not independent events; only 3 test runs per scenario.",
        "Synthetic Unreal scenarios only, not demonstrated real factory performance.",
        "No dedicated Warning-then-recovery-only runs.",
        "Exact Error timestamps absent; Detector event logs required for exact lead-time evaluation.",
        "Blank endpoint cannot identify Error onset; no independent reason labels in either CSV.",
        "Uncalibrated model probabilities; threshold selected for validation Macro F1, not safety certification.",
    ]
    write_json(output / "evaluation.json", results)
    checksums = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in output.iterdir()
        if p.is_file()
    }
    write_json(output / "artifact_checksums.json", checksums)
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "selected": chosen,
                "test": {k: v for k, v in results["test"].items() if k != "per_run"},
                "benchmark": results["benchmark"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["validate", "train", "benchmark", "evaluate-probabilities"]
    )
    parser.add_argument(
        "--csv",
        required=True,
        action="append",
        type=Path,
        help="원본 CSV. 여러 파일은 --csv를 반복해서 지정",
    )
    parser.add_argument("--output", required=True, type=Path)
    split_options = parser.add_mutually_exclusive_group()
    split_options.add_argument("--manifest", type=Path)
    split_options.add_argument(
        "--extend-manifest",
        type=Path,
        help="기존 실행 배정을 보존하고 새 시나리오만 분리",
    )
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        _, audit = load_dataset(args.csv)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, audit)
        print(json.dumps(audit, indent=2, ensure_ascii=False))
    elif args.command == "evaluate-probabilities":
        if args.model is None or args.manifest is None:
            parser.error("evaluate-probabilities requires --model and --manifest")
        if args.output.exists():
            parser.error("output exists; choose a new report path")
        groups, audit = load_dataset(args.csv)
        manifest = json.loads(args.manifest.read_text())
        validate_manifest(manifest, groups, audit["sha256"])
        predictor = FutureErrorPredictor.load(args.model)
        if predictor.metadata["dataset_sha256"] != audit["sha256"]:
            parser.error("model dataset hash mismatch")
        result = {
            "model_version": predictor.metadata["model_version"],
            "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
            "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            "dataset_sha256": audit["sha256"],
            "probability_calibration": "none; existing fixed model, no fitting or selection",
            "sets": {},
        }
        for name, runs in manifest["splits"].items():
            records, _ = build_windows(groups, runs, audit["timestamp_order_issues"])
            x, y = matrix(records)
            probabilities = predictor.model.predict_proba(x)
            summary = probability_metrics(y, probabilities, predictor.model.classes_)
            run_ids = np.array([r["run_id"] for r in records])
            summary["per_run"] = {
                run: probability_metrics(
                    y[run_ids == run],
                    probabilities[run_ids == run],
                    predictor.model.classes_,
                )
                for run in sorted(set(run_ids))
            }
            result["sets"][name] = summary
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, result)
        print(
            json.dumps(
                {
                    name: {
                        k: s[k]
                        for k in ("support", "log_loss", "multiclass_brier_score")
                    }
                    for name, s in result["sets"].items()
                },
                indent=2,
            )
        )
    elif args.command == "benchmark":
        if args.model is None or args.manifest is None:
            parser.error("benchmark requires --model and --manifest")
        groups, audit = load_dataset(args.csv)
        manifest = json.loads(args.manifest.read_text())
        validate_manifest(manifest, groups, audit["sha256"])
        records, _ = build_windows(
            groups, manifest["splits"]["test"], audit["timestamp_order_issues"]
        )
        predictor = FutureErrorPredictor.load(args.model)
        result = benchmark(predictor, groups, records)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        train(
            args.csv,
            args.output,
            args.manifest,
            extend_manifest_path=args.extend_manifest,
        )


if __name__ == "__main__":
    main()
