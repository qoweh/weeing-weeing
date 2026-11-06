"""백엔드가 나중에 사용할 독립 추론 경계. 서버/Detector에 연결하지 않는다."""

import numpy as np

from .features import (
    CLASSES,
    FEATURE_NAMES,
    InvalidWindowError,
    classes_for_codes,
    extract_features,
)


def model_classes(model):
    labels = list(model.classes_)
    if (
        "NO_ERROR" not in labels
        or len(labels) != len(set(labels))
        or set(labels) != set(classes_for_codes([c for c in labels if c != "NO_ERROR"]))
    ):
        raise ValueError("Model classes invalid")
    return labels


def probability_map(model, features):
    """확률 순서는 반드시 학습 모델의 classes_에서 읽는다."""
    labels = model_classes(model)
    values = model.predict_proba(np.asarray(features).reshape(1, -1))[0]
    if (
        not np.isfinite(values).all()
        or np.any(values < 0)
        or not np.isclose(sum(values), 1)
    ):
        raise ValueError("Invalid model probabilities")
    return {str(c): float(p) for c, p in zip(labels, values, strict=True)}


class FutureErrorPredictor:
    def __init__(self, model, metadata):
        if metadata["feature_names"] != FEATURE_NAMES:
            raise ValueError("Feature schema mismatch")
        labels = model_classes(model)
        expected = metadata.get("classes", CLASSES)
        if set(labels) != set(expected) or (
            "classes" in metadata and labels != expected
        ):
            raise ValueError("Model classes mismatch")
        self.classes = labels
        self.supported_fault_codes = [str(c) for c in labels if c != "NO_ERROR"]
        self.model = model
        self.metadata = metadata

    @classmethod
    def load(cls, path):
        """신뢰하는 로컬 joblib만 로드한다(pickle은 코드 실행 가능)."""
        import joblib

        bundle = joblib.load(path)
        return cls(bundle["model"], bundle["metadata"])

    def predict(self, rows, as_of=None):
        """rows: timestamp와 센서 10개 dict 목록. 0.5초마다 호출, 재학습 없음.

        최소 30초 이력과 왼쪽 경계 표본을 포함한다. 부적합 입력에는 확률이 없다.
        as_of 생략 시 마지막 표본 시각이 t. 현재 실제 Error 여부는 Detector가 담당한다.
        """
        base = {
            "model_version": self.metadata["model_version"],
            "input_valid": False,
            "reference_time": None,
            "probabilities": None,
            "supported_fault_codes": self.supported_fault_codes,
        }
        try:
            features, quality = extract_features(rows, as_of)
        except InvalidWindowError as exc:
            reason = str(exc)
            return {
                **base,
                "status": "not_ready"
                if reason == "insufficient_history"
                else "invalid_input",
                "reason": reason,
            }
        probabilities = probability_map(self.model, features)
        no_error = probabilities["NO_ERROR"]
        top3 = sorted(
            ((c, p) for c, p in probabilities.items() if c != "NO_ERROR"),
            key=lambda item: (-item[1], item[0]),
        )[:3]
        error_probability = 1 - no_error
        return {
            **base,
            "status": "ready",
            "input_valid": True,
            "reference_time": quality["reference_time"],
            "quality": quality,
            "probabilities": probabilities,
            "no_error_probability": no_error,
            "error_probability": error_probability,
            "fault_top3": [{"code": c, "confidence": p} for c, p in top3],
            "warning_threshold": self.metadata["warning_threshold"],
            "warning": error_probability >= self.metadata["warning_threshold"],
            "probability_kind": "uncalibrated_model_prediction",
            "horizon": "(reference_time, reference_time + 60 seconds]",
        }


def create_live_service(**options):
    """API에서 사용할 유한 큐 기반 관찰 전용 추론 서비스 생성 경계."""
    from .live import LivePredictionService

    return LivePredictionService(**options)
