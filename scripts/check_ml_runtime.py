"""배포 장비 내 합성 입력 추론 점검. 실제 센서·Detector·DB·LLM에는 요청하지 않는다."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, quantiles
from time import perf_counter

from weeing_weeing.ml.interface import FutureErrorPredictor


def main():
    path = Path("/app/models/future_error.joblib")
    manifest = json.loads(path.with_name("manifest.json").read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Model checksum mismatch")
    predictor = FutureErrorPredictor.load(path)
    start = datetime.now(UTC) - timedelta(seconds=30)
    rows = [
        {
            "timestamp": (start + timedelta(seconds=i * 0.5)).isoformat(),
            "infeed_present": False,
            "outfeed_present": False,
            "rpm": 1019.7,
            "dc_input_current_a": 0.2,
            "dc_bus_voltage_v": 24.0,
            "motor_housing_temp_c": 30.0,
            "de_vibration_rms_g": 0.05,
            "de_kurtosis": 3.0,
            "nde_vibration_rms_g": 0.05,
            "nde_kurtosis": 3.0,
        }
        for i in range(61)
    ]
    for _ in range(5):
        predictor.predict(rows)
    elapsed = []
    for _ in range(200):
        before = perf_counter()
        result = predictor.predict(rows)
        elapsed.append((perf_counter() - before) * 1000)
        assert result["status"] == "ready"
        assert len(result["probabilities"]) == 5
        assert abs(sum(result["probabilities"].values()) - 1) < 1e-9
    print(
        json.dumps(
            {
                "mode": "synthetic_local_inference_smoke",
                "model_version": predictor.metadata["model_version"],
                "repeats": len(elapsed),
                "mean_ms": mean(elapsed),
                "p95_ms": quantiles(elapsed, n=100)[94],
                "max_ms": max(elapsed),
                "observed_under_500ms": max(elapsed) < 500,
            }
        )
    )
    if max(elapsed) >= 500:
        raise RuntimeError("Inference deadline exceeded")


if __name__ == "__main__":
    main()
