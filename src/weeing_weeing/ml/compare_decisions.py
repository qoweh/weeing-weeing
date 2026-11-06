"""고정 모델·분리에서 전체 클래스 Top 1과 기존 Error 임계값 분류 비교."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .data import build_windows, load_dataset, validate_manifest
from .experiment import matrix, metrics, write_json
from .interface import FutureErrorPredictor


def decision_pair(probabilities, classes, threshold):
    """두 방식은 같은 확률 사용. 동률은 model.classes_의 첫 클래스로 결정."""
    p = np.asarray(probabilities)
    labels = np.asarray(classes)
    normal = list(classes).index("NO_ERROR")
    faults = np.flatnonzero(labels != "NO_ERROR")
    winner = faults[p[:, faults].argmax(axis=1)]
    return {
        "error_threshold": np.where(
            1 - p[:, normal] >= threshold, labels[winner], "NO_ERROR"
        ),
        "all_class_top1": labels[p.argmax(axis=1)],
    }


def compare(csv_paths, model_path, manifest_path, output):
    output = Path(output)
    if output.exists():
        raise ValueError("Output exists; choose a new report path")
    model_path, manifest_path = Path(model_path), Path(manifest_path)
    predictor = FutureErrorPredictor.load(model_path)
    groups, audit = load_dataset(csv_paths)
    manifest = json.loads(manifest_path.read_text())
    validate_manifest(manifest, groups, audit["sha256"])
    if predictor.metadata["dataset_sha256"] != audit["sha256"]:
        raise ValueError("Model dataset hash mismatch")
    threshold = predictor.metadata["warning_threshold"]
    result = {
        "model_version": predictor.metadata["model_version"],
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "dataset_sha256": audit["sha256"],
        "error_threshold": threshold,
        "tie_breaking": "first index in model.classes_, numpy.argmax",
        "scope": "descriptive comparison only; no refitting, selection or inference changes",
        "probability_metrics": "identical for both methods: same unmodified probabilities",
        "sets": {},
    }
    for name, runs in manifest["splits"].items():
        records, _ = build_windows(groups, runs, audit["timestamp_order_issues"])
        x, y = matrix(records)
        p = predictor.model.predict_proba(x)
        predictions = decision_pair(p, predictor.classes, threshold)
        run_ids = np.array([r["run_id"] for r in records])
        summary = {"windows": len(y), "runs": len(runs), "methods": {}}
        for method, predicted in predictions.items():
            m = metrics(y, predicted, predictor.classes)
            fault = y != "NO_ERROR"
            m["any_error_recall"] = float(np.mean(predicted[fault] != "NO_ERROR"))
            m["missed_fault_windows"] = int(np.sum(fault & (predicted == "NO_ERROR")))
            m["false_alarm_windows"] = int(np.sum(~fault & (predicted != "NO_ERROR")))
            m["wrong_fault_code_windows"] = int(
                np.sum(fault & (predicted != "NO_ERROR") & (predicted != y))
            )
            m["per_run"] = {
                run: metrics(
                    y[run_ids == run], predicted[run_ids == run], predictor.classes
                )
                for run in sorted(set(run_ids))
            }
            summary["methods"][method] = m
        changed = predictions["error_threshold"] != predictions["all_class_top1"]
        normal = y == "NO_ERROR"
        summary["changed_windows"] = int(changed.sum())
        summary["changes_on_no_error"] = int(np.sum(changed & normal))
        summary["changes_on_fault"] = int(np.sum(changed & ~normal))
        summary["exact_top1_ties"] = int(
            np.sum((p == p.max(axis=1, keepdims=True)).sum(axis=1) > 1)
        )
        result["sets"][name] = summary
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, result)
    print(
        json.dumps(
            {
                name: {
                    method: {
                        k: m[k]
                        for k in [
                            "accuracy",
                            "macro_f1",
                            "no_error_false_alarm_rate",
                            "any_error_recall",
                            "false_alarm_windows",
                            "missed_fault_windows",
                        ]
                    }
                    for method, m in s["methods"].items()
                }
                for name, s in result["sets"].items()
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, action="append", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compare(args.csv, args.model, args.manifest, args.output)


if __name__ == "__main__":
    main()
