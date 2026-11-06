"""보정하지 않은 확률의 품질 평가. 클래스 순서는 호출자가 명시한다."""

import numpy as np


def binary_metrics(observed, probabilities, bins=10):
    """Brier(0~1)와 동일 너비 구간별 신뢰도. 마지막 구간만 오른쪽 포함."""
    observed = np.asarray(observed, dtype=float)
    probabilities = np.asarray(probabilities, dtype=float)
    indices = np.minimum((probabilities * bins).astype(int), bins - 1)
    reliability = []
    error = 0.0
    for i in range(bins):
        selected = indices == i
        count = int(selected.sum())
        mean = float(probabilities[selected].mean()) if count else None
        frequency = float(observed[selected].mean()) if count else None
        if count:
            error += count * abs(mean - frequency)
        reliability.append(
            {
                "lower": i / bins,
                "upper": (i + 1) / bins,
                "count": count,
                "mean_probability": mean,
                "observed_frequency": frequency,
            }
        )
    return {
        "support": len(observed),
        "positive_support": int(observed.sum()),
        "brier_score": float(np.mean((probabilities - observed) ** 2)),
        "ece_equal_width": error / len(observed),
        "reliability_bins": reliability,
    }


def probability_metrics(y, probabilities, classes, bins=10):
    """Multiclass Brier=sum_k(p_k-y_k)^2(0~2), Log Loss=자연로그.

    클래스 순서 변경에도 결과를 보존한다. ECE는 구간 설정에 의존하는 보조 지표다.
    """
    y = np.asarray(y)
    p = np.asarray(probabilities, dtype=float)
    classes = list(classes)
    if (
        y.ndim != 1
        or not len(y)
        or not isinstance(bins, int)
        or bins < 1
        or len(classes) < 2
        or len(set(classes)) != len(classes)
        or "NO_ERROR" not in classes
        or not set(y).issubset(classes)
        or p.shape != (len(y), len(classes))
        or not np.isfinite(p).all()
        or np.any((p < 0) | (p > 1))
        or not np.allclose(p.sum(axis=1), 1, atol=1e-8, rtol=0)
    ):
        raise ValueError("Invalid probability evaluation inputs")
    truth = y[:, None] == np.asarray(classes)[None, :]
    correct = p[truth]
    normal = classes.index("NO_ERROR")
    return {
        "support": len(y),
        "classes": classes,
        "log_loss": float(-np.log(np.clip(correct, np.finfo(float).eps, 1)).mean()),
        "multiclass_brier_score": float(np.mean(np.sum((p - truth) ** 2, axis=1))),
        "any_error": binary_metrics(y != "NO_ERROR", 1 - p[:, normal], bins),
        "per_class": {
            label: binary_metrics(truth[:, i], p[:, i], bins)
            for i, label in enumerate(classes)
        },
        "definitions": {
            "log_loss": "natural log, true-class probabilities clipped at float64 epsilon",
            "multiclass_brier_score": "mean(sum_k((p_k-y_k)^2)), range [0,2]",
            "binary_brier_score": "mean((p-y)^2), range [0,1]",
            "ece_equal_width": "sum_bin(n_bin/N * abs(mean_p-positive_frequency))",
            "bins": bins,
            "bin_intervals": "[lower,upper), last interval includes 1",
            "weighting": "equal weight per window; overlapping windows are correlated",
        },
    }
