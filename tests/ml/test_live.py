import hashlib
import time
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

pytest.importorskip("sklearn")

from weeing_weeing.ml.features import SENSORS  # noqa: E402
from weeing_weeing.ml.live import LivePredictionService  # noqa: E402


def eventually(check):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.005)
    assert check()


class Predictor:
    metadata = {"model_version": "test-live-v1"}

    def predict(self, rows):
        from weeing_weeing.ml.features import InvalidWindowError, extract_features

        try:
            _, quality = extract_features(rows)
        except InvalidWindowError as error:
            return {
                "status": "not_ready"
                if str(error) == "insufficient_history"
                else "invalid_input",
                "reason": str(error),
                "input_valid": False,
                "probabilities": None,
            }
        return {
            "status": "ready",
            "input_valid": True,
            "probabilities": {"NO_ERROR": 0.8},
            "quality": quality,
            "reference_time": quality["reference_time"],
        }


@pytest.fixture
def service(tmp_path):
    path = tmp_path / "model.joblib"
    path.write_bytes(b"test-only-no-pickle")
    svc = LivePredictionService(
        enabled=True,
        model_path=path,
        model_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        output_dir=tmp_path / "log",
        predictor_loader=lambda _: Predictor(),
    ).start()
    eventually(lambda: svc.loaded)
    yield svc
    svc.stop()


def row(i):
    return {
        **dict.fromkeys(SENSORS, 1.0),
        "infeed_present": False,
        "outfeed_present": True,
        "timestamp": (
            datetime(2026, 11, 4, tzinfo=UTC) + timedelta(seconds=i / 2)
        ).isoformat(),
        "record_id": f"record-{i}",
        "process_id": "process",
        "asset_id": "asset",
    }


def submit_wait(service, run, data, errors=None):
    before = service.counters["completed"]
    service.submit(run, data, errors or [])
    eventually(lambda: service.counters["completed"] > before)


def test_warmup_features_no_training_reconnect_and_staleness(service):
    service.begin("one")
    for i in range(61):
        submit_wait(service, "one", row(i))
    state = service.snapshot()
    assert state["prediction_usable"]
    assert state["prediction"]["quality"]["sample_count"] == 60
    assert state["prediction"]["evaluation_eligible"]
    assert state["prediction"]["mode"] == "observation_only"
    service.result_clock -= 4
    assert not service.snapshot()["prediction_usable"]
    service.end("one")
    assert service.snapshot()["stale"]
    service.begin("two")
    submit_wait(service, "two", row(62), ["BTT2-M02"])
    assert service.snapshot()["prediction"]["status"] == "not_ready"
    assert not service.snapshot()["prediction"]["evaluation_eligible"]
    assert len(service.recent()) == 1
    eventually(lambda: bool(list(service.output_dir.glob("*.jsonl"))))


def test_supported_codes_follow_loaded_predictor_even_during_warmup(
    service, monkeypatch
):
    expected = ["BTT2-M03", "BTT2-M18"]
    monkeypatch.setattr(Predictor, "supported_fault_codes", expected, raising=False)
    service.begin("expanded")
    submit_wait(service, "expanded", row(0))
    result = service.snapshot()["prediction"]
    assert result["status"] == "not_ready"
    assert result["supported_fault_codes"] == expected


def test_missing_gap_order_and_none_not_fabricated_normal(service):
    service.begin("one")
    for i in range(62):
        if i not in (28, 29, 30):
            submit_wait(service, "one", row(i))
    assert service.snapshot()["prediction"]["reason"] == "gap_over_1_5s"
    submit_wait(service, "one", row(61))
    assert service.snapshot()["prediction"]["reason"] == "timestamp_order"
    assert service.snapshot()["prediction"]["probabilities"] is None


def test_checksum_checked_before_model_loader(tmp_path):
    path = tmp_path / "bad.joblib"
    path.write_bytes(b"not-a-model")
    called = []
    svc = LivePredictionService(
        enabled=True,
        model_path=path,
        model_sha256="a" * 64,
        output_dir=tmp_path,
        predictor_loader=lambda p: called.append(p),
    ).start()
    try:
        eventually(lambda: svc.snapshot()["prediction"]["status"] == "model_error")
        assert not called
    finally:
        svc.stop()


def test_slow_inference_does_not_block_dispatch_or_publish_old_session(service):
    entered, release = Event(), Event()

    class Slow:
        def predict(self, rows):
            entered.set()
            assert release.wait(5)
            return {"status": "ready", "input_valid": True, "probabilities": {}}

    service.loader = None
    # worker의 모델을 교체하지 않고 실제 예측 메서드만 지연한다.
    original = Predictor.predict
    Predictor.predict = Slow.predict
    try:
        service.begin("one")
        started = time.monotonic()
        service.submit("one", row(0), [])
        assert time.monotonic() - started < 0.1
        assert entered.wait(5)
        for i in range(1, 20):
            service.submit("one", row(i), [])
        assert service.snapshot()["counters"]["dropped"] > 0
        service.begin("two")
        release.set()
        eventually(lambda: service.queue.empty())
        assert service.snapshot()["prediction"]["status"] == "not_ready"
        assert service.snapshot()["run_id"] == "two"
        assert not service.recent()
    finally:
        release.set()
        Predictor.predict = original


def test_image_manifest_fallback_and_atomic_session_snapshot(tmp_path):
    import json

    path = tmp_path / "model.joblib"
    path.write_bytes(b"fake-immutable-image-model")
    path.with_name("manifest.json").write_text(
        json.dumps({"sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    )
    service = LivePredictionService(
        enabled=True,
        model_path=path,
        model_sha256="",
        output_dir=tmp_path / "logs",
        predictor_loader=lambda _: Predictor(),
    ).start()
    try:
        eventually(lambda: service.loaded)
        service.begin("one")
        submit_wait(service, "one", row(0))
        response = service.recent_snapshot(50)
        assert all(
            item["run_id"] == response["state"]["run_id"] for item in response["items"]
        )
        service.begin("two")
        assert service.recent_snapshot()["items"] == []
    finally:
        service.stop()


def test_completed_late_result_is_not_usable(service, monkeypatch):
    def slow(self, rows):
        time.sleep(0.55)
        return {"status": "ready", "input_valid": True, "probabilities": {}}

    monkeypatch.setattr(Predictor, "predict", slow)
    service.begin("one")
    submit_wait(service, "one", row(0))
    result = service.snapshot()
    assert result["age_seconds"] >= 0.5
    assert result["prediction"]["deadline_exceeded"]
    assert not result["prediction_usable"]
