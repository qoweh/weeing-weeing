import numpy as np
import pytest

pytest.importorskip("joblib")
pytest.importorskip("sklearn")

from weeing_weeing.ml.compare_decisions import decision_pair


def test_top1_includes_normal_and_differs_from_summed_error():
    classes = ["BTT2-M10", "NO_ERROR", "BTT2-M02"]
    p = np.array([[0.35, 0.45, 0.2], [0.4, 0.3, 0.3], [0.1, 0.8, 0.1]])
    result = decision_pair(p, classes, 0.5)
    assert result["error_threshold"].tolist() == ["BTT2-M10", "BTT2-M10", "NO_ERROR"]
    assert result["all_class_top1"].tolist() == ["NO_ERROR", "BTT2-M10", "NO_ERROR"]
    perm = [1, 2, 0]
    reordered = decision_pair(p[:, perm], [classes[i] for i in perm], 0.5)
    for method, predicted in result.items():
        np.testing.assert_array_equal(predicted, reordered[method])
    np.testing.assert_array_equal(p[0], [0.35, 0.45, 0.2])


def test_exact_tie_uses_first_model_class_and_threshold_is_inclusive():
    result = decision_pair([[0.5, 0.5]], ["NO_ERROR", "BTT2-M10"], 0.5)
    assert result["error_threshold"].tolist() == ["BTT2-M10"]
    assert result["all_class_top1"].tolist() == ["NO_ERROR"]
