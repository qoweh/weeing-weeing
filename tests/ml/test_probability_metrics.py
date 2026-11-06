"""확률 지표의 수치 정의·클래스 정렬·빈 구간/희소 실행 검증."""

import numpy as np
import pytest

from weeing_weeing.ml.experiment import evaluate
from weeing_weeing.ml.probability_metrics import probability_metrics


def test_known_scores_and_class_order():
    y = np.array(["NO_ERROR", "BTT2-M02"])
    p = np.array([[0.8, 0.1, 0.1], [0.2, 0.7, 0.1]])
    classes = ["NO_ERROR", "BTT2-M02", "BTT2-M03"]
    result = probability_metrics(y, p, classes)
    assert result["log_loss"] == pytest.approx(-np.log([0.8, 0.7]).mean())
    assert result["multiclass_brier_score"] == pytest.approx(0.1)
    assert result["any_error"]["brier_score"] == pytest.approx(0.04)
    assert result["per_class"]["BTT2-M03"]["positive_support"] == 0
    perm = [2, 0, 1]
    reordered = probability_metrics(y, p[:, perm], [classes[i] for i in perm])
    assert reordered["log_loss"] == pytest.approx(result["log_loss"])
    assert reordered["multiclass_brier_score"] == pytest.approx(0.1)
    assert reordered["any_error"] == result["any_error"]
    assert reordered["per_class"] == result["per_class"]


def test_bin_boundaries_empty_bins_and_confident_wrong_prediction():
    result = probability_metrics(
        ["NO_ERROR", "BTT2-M02"], [[1, 0], [0, 1]], ["NO_ERROR", "BTT2-M02"]
    )
    assert result["log_loss"] == 0
    assert result["multiclass_brier_score"] == 0
    binary = result["any_error"]
    assert binary["ece_equal_width"] == 0
    assert binary["reliability_bins"][0]["count"] == 1
    assert binary["reliability_bins"][-1]["count"] == 1
    assert binary["reliability_bins"][1]["mean_probability"] is None
    assert binary["reliability_bins"][1]["observed_frequency"] is None
    wrong = probability_metrics(["NO_ERROR"], [[0, 1]], ["NO_ERROR", "BTT2-M02"])
    assert np.isfinite(wrong["log_loss"]) and wrong["log_loss"] > 30
    assert wrong["multiclass_brier_score"] == 2
    assert wrong["any_error"]["brier_score"] == 1


@pytest.mark.parametrize(
    "y,p,classes",
    [
        ([], [], ["NO_ERROR", "BTT2-M02"]),
        (["unknown"], [[0.5, 0.5]], ["NO_ERROR", "BTT2-M02"]),
        (["NO_ERROR"], [[0.5, 0.5]], ["NO_ERROR", "NO_ERROR"]),
        (["NO_ERROR"], [[0.2, 0.2]], ["NO_ERROR", "BTT2-M02"]),
        (["NO_ERROR"], [[-0.1, 1.1]], ["NO_ERROR", "BTT2-M02"]),
        (["NO_ERROR"], [[float("nan"), 0]], ["NO_ERROR", "BTT2-M02"]),
        (["NO_ERROR"], [[0.5, 0.3, 0.2]], ["NO_ERROR", "BTT2-M02"]),
    ],
)
def test_invalid_inputs_rejected(y, p, classes):
    with pytest.raises(ValueError, match="Invalid probability"):
        probability_metrics(y, p, classes)


def test_evaluate_uses_model_probability_order_not_report_order():
    class Model:
        classes_ = np.array(["BTT2-M02", "NO_ERROR"])

        def predict_proba(self, x):
            return np.array([[0.7, 0.3], [0.1, 0.9]])

    records = [
        {"features": [0], "target": "BTT2-M02", "run_id": "fault"},
        {"features": [1], "target": "NO_ERROR", "run_id": "normal"},
    ]
    report, predictions = evaluate(
        Model(), records, 0.5, classes=["NO_ERROR", "BTT2-M02"]
    )
    assert list(predictions) == ["BTT2-M02", "NO_ERROR"]
    assert report["probability_metrics"]["classes"] == ["BTT2-M02", "NO_ERROR"]
    assert report["probability_metrics"]["log_loss"] == pytest.approx(
        -np.log([0.7, 0.9]).mean()
    )
