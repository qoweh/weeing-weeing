"""원본 CSV 검증 → 실행 단위 분리 → 원본 이력으로 시간 구간 생성."""

import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np

from .features import (
    CLASSES,
    SENSORS,
    InvalidWindowError,
    classes_for_codes,
    extract_features,
    sensor_value,
    utc_timestamp,
)

COLUMNS = [
    "record_id",
    "timestamp",
    "process_id",
    "asset_id",
    "schema_version",
    *SENSORS,
    "target_label",
    "run_id",
]
EXPECTED_LABELS = dict(
    zip(CLASSES + [""], [16185, 1794, 1797, 1797, 1792, 13909], strict=True)
)
CODES = CLASSES[1:]
SEED = 20261104


def scenario(run_id):
    match = re.fullmatch(r"ml-([MP]\d{2})-fault-\d+-[a-f0-9]+-[a-f0-9]+", run_id)
    if not match:
        raise ValueError(f"Unknown run_id format: {run_id}")
    code = "BTT2-" + match[1]
    classes_for_codes([code])
    return code


def _load_source(path):
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"CSV schema/order mismatch: {reader.fieldnames}")
        rows = list(reader)
    groups = defaultdict(list)
    issues = Counter()
    for r in rows:
        if None in r or any(v is None for v in r.values()):
            raise ValueError("Malformed CSV row")
        r["timestamp"] = utc_timestamp(r["timestamp"])
        code = scenario(r["run_id"])
        if r["target_label"] not in ("", "NO_ERROR", code):
            raise ValueError("Label conflicts with run scenario")
        for c in SENSORS:
            if not r[c].strip():
                issues[f"{c}:missing"] += 1
            try:
                if not np.isfinite(sensor_value(c, r[c])):
                    issues[f"{c}:nonfinite"] += 1
            except (ValueError, TypeError, OverflowError):
                issues[f"{c}:invalid"] += 1
        groups[r["run_id"]].append(r)
    duplicates = len(rows) - len({r["record_id"] for r in rows})
    if duplicates or any(not r["record_id"] for r in rows):
        raise ValueError(f"record_id invalid/duplicate: {duplicates}")
    counts = Counter(r["target_label"] for r in rows)
    run_issues = {}
    for run, group in groups.items():
        times = [r["timestamp"] for r in group]
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        if any(x <= 0 for x in gaps):
            run_issues[run] = "timestamp_order"
        if any(
            len({r[c] for r in group}) != 1
            for c in ("asset_id", "process_id", "schema_version")
        ):
            raise ValueError(f"Management fields change within run: {run}")
    differences = {}
    classes = classes_for_codes(sorted({scenario(r) for r in groups}))
    legacy_profile = set(classes) <= set(CLASSES)
    if legacy_profile and len(rows) != 37274:
        differences["rows"] = {"expected": 37274, "actual": len(rows)}
    if legacy_profile and dict(counts) != EXPECTED_LABELS:
        differences["labels"] = {"expected": EXPECTED_LABELS, "actual": dict(counts)}
    report = {
        "source_path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rows": len(rows),
        "classes": classes,
        "reference_counts_profile": "original_four_faults_v1"
        if legacy_profile
        else None,
        "columns": COLUMNS,
        "labels": dict(counts),
        "runs": len(groups),
        "runs_by_code": dict(Counter(scenario(r) for r in groups)),
        "duplicate_record_ids": duplicates,
        "sensor_issues": dict(issues),
        "timestamp_order_issues": run_issues,
        "sample_gap_seconds": {
            "min": min(
                (
                    (b["timestamp"] - a["timestamp"]).total_seconds()
                    for g in groups.values()
                    for a, b in zip(g, g[1:])
                ),
                default=None,
            ),
            "max": max(
                (
                    (b["timestamp"] - a["timestamp"]).total_seconds()
                    for g in groups.values()
                    for a, b in zip(g, g[1:])
                ),
                default=None,
            ),
        },
        "gaps_over_0_8s": sum(
            (b["timestamp"] - a["timestamp"]).total_seconds() > 0.8
            for g in groups.values()
            for a, b in zip(g, g[1:])
        ),
        "differences_from_supplied_counts": differences,
        "blank_label_reasons": "CSV alone cannot distinguish already Error vs insufficient future",
    }
    return dict(groups), report


def load_dataset(paths):
    """여러 원본 CSV를 검증한다. 실행/레코드 중복을 몰래 이어 붙이지 않는다."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    if not paths:
        raise ValueError("At least one CSV required")
    merged, sources, identifiers = {}, [], set()
    for path in paths:
        groups, audit = _load_source(path)
        if set(merged) & set(groups):
            raise ValueError("run_id overlaps between source files")
        current = {row["record_id"] for group in groups.values() for row in group}
        if identifiers & current:
            raise ValueError("record_id overlaps between source files")
        identifiers.update(current)
        merged.update(groups)
        sources.append(audit)
    if len(sources) == 1:
        audit = dict(sources[0])
    else:
        counts, issues, order_issues = Counter(), Counter(), {}
        for source in sources:
            counts.update(source["labels"])
            issues.update(source["sensor_issues"])
            order_issues.update(source["timestamp_order_issues"])
        audit = {
            "sha256": hashlib.sha256(
                json.dumps(sorted(s["sha256"] for s in sources)).encode()
            ).hexdigest(),
            "rows": sum(s["rows"] for s in sources),
            "columns": COLUMNS,
            "classes": classes_for_codes(sorted({scenario(r) for r in merged})),
            "labels": dict(counts),
            "runs": len(merged),
            "runs_by_code": dict(Counter(scenario(r) for r in merged)),
            "duplicate_record_ids": 0,
            "sensor_issues": dict(issues),
            "timestamp_order_issues": order_issues,
            "sample_gap_seconds": {
                key: fn(
                    (
                        s["sample_gap_seconds"][key]
                        for s in sources
                        if s["sample_gap_seconds"][key] is not None
                    ),
                    default=None,
                )
                for key, fn in (("min", min), ("max", max))
            },
            "gaps_over_0_8s": sum(s["gaps_over_0_8s"] for s in sources),
            "differences_from_supplied_counts": {
                s["source_path"]: s["differences_from_supplied_counts"]
                for s in sources
                if s["differences_from_supplied_counts"]
            },
            "blank_label_reasons": "CSV alone cannot distinguish already Error vs insufficient future",
        }
    audit["sources"] = sources
    audit["dataset_hash_definition"] = (
        "single file SHA256, or SHA256 of sorted source SHA256 JSON list"
    )
    return merged, audit


def split_runs(groups, digest, previous_manifest=None, source_digests=()):
    rng = random.Random(SEED)
    splits = {"train": [], "validation": [], "test": []}
    codes = sorted({scenario(r) for r in groups})
    preserved = set()
    if previous_manifest is not None:
        old_digest = previous_manifest["dataset_sha256"]
        if old_digest not in source_digests:
            raise ValueError("Previous manifest source hash not present")
        previous_runs = {
            r for runs in previous_manifest["splits"].values() for r in runs
        }
        if not previous_runs <= set(groups):
            raise ValueError("Previous manifest runs missing from dataset")
        validate_manifest(
            previous_manifest, {r: groups[r] for r in previous_runs}, old_digest
        )
        for name in splits:
            splits[name].extend(previous_manifest["splits"][name])
        preserved = {scenario(r) for r in previous_runs}
    for code in codes:
        runs = sorted(r for r in groups if scenario(r) == code)
        if len(runs) != 15:
            raise ValueError(f"{code}: expected 15 runs, got {len(runs)}")
        if code in preserved:
            continue
        rng.shuffle(runs)
        for name, part in zip(splits, [runs[:9], runs[9:12], runs[12:]], strict=True):
            splits[name].extend(part)
    manifest = {"seed": SEED, "dataset_sha256": digest, "splits": splits}
    manifest["classes"] = classes_for_codes(codes)
    if previous_manifest is not None:
        manifest["extended_from"] = {
            "dataset_sha256": previous_manifest["dataset_sha256"],
            "manifest_sha256": hashlib.sha256(
                json.dumps(previous_manifest, sort_keys=True).encode()
            ).hexdigest(),
            "preserved_runs": sum(len(v) for v in previous_manifest["splits"].values()),
        }
    validate_manifest(manifest, groups, digest)
    return manifest


def validate_manifest(manifest, groups, digest):
    if manifest["dataset_sha256"] != digest:
        raise ValueError("Manifest dataset hash mismatch")
    splits = manifest["splits"]
    if set(splits) != {"train", "validation", "test"}:
        raise ValueError("Manifest split names mismatch")
    all_runs = [r for runs in splits.values() for r in runs]
    if len(all_runs) != len(set(all_runs)) or set(all_runs) != set(groups):
        raise ValueError("Manifest run overlap/missing/unknown")
    codes = sorted({scenario(r) for r in groups})
    if manifest.get("classes", classes_for_codes(codes)) != classes_for_codes(codes):
        raise ValueError("Manifest classes mismatch")
    for name, runs in splits.items():
        expected = 9 if name == "train" else 3
        if Counter(scenario(r) for r in runs) != dict.fromkeys(codes, expected):
            raise ValueError("Manifest scenario allocation mismatch")


def build_windows(groups, runs, run_issues=None):
    records = []
    summaries = {}
    for run in runs:
        raw = groups[run]
        ordered = sorted(raw, key=lambda r: r["timestamp"])
        times = np.array([r["timestamp"].timestamp() for r in ordered])
        excluded = Counter()
        labels = Counter()
        candidates = 0
        grid = ordered[0]["timestamp"]
        while grid <= ordered[-1]["timestamp"]:
            end = int(np.searchsorted(times, grid.timestamp(), side="right"))
            anchor = ordered[end - 1]
            candidates += 1
            try:
                if run_issues and run in run_issues:
                    raise InvalidWindowError(run_issues[run])
                # 경계 직전 표본 한 개를 포함. 빈 라벨 행도 원본 그대로 유지한다.
                left = anchor["timestamp"].timestamp() - 30
                start = max(0, int(np.searchsorted(times, left, side="right")) - 1)
                features, quality = extract_features(
                    ordered[start:end], anchor["timestamp"]
                )
                if not anchor["target_label"]:
                    raise InvalidWindowError("blank_endpoint_label")
                labels[anchor["target_label"]] += 1
                records.append(
                    {
                        "run_id": run,
                        "target": anchor["target_label"],
                        "reference_time": quality["reference_time"],
                        "features": features,
                        "start_index": start,
                        "end_index": end,
                    }
                )
            except InvalidWindowError as exc:
                excluded[str(exc)] += 1
            grid += timedelta(seconds=3)
        summaries[run] = {
            "code": scenario(run),
            "rows": len(raw),
            "raw_labels": dict(Counter(r["target_label"] for r in raw)),
            "candidates": candidates,
            "windows": sum(labels.values()),
            "labels": dict(labels),
            "excluded": dict(excluded),
        }
    if not records:
        raise ValueError("No valid labeled windows")
    return records, summaries
