import hashlib
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from weeing_weeing.api.app import app
from weeing_weeing.contracts import Role, TelemetryRecord, UserAccount
from weeing_weeing.db import interface as db
from weeing_weeing.ml.features import CLASSES, FEATURE_NAMES
from weeing_weeing.ml.interface import FutureErrorPredictor


class Model:
    classes_ = np.array(CLASSES)

    def predict_proba(self, values):
        return np.tile([0.7, 0.1, 0.05, 0.05, 0.1], (len(values), 1))


def wait_result(client, headers, record_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = client.get("/ml/prediction", headers=headers).json()
        if result["prediction"].get("record_id") == record_id:
            return result
        time.sleep(0.005)
    pytest.fail("ML result not published")


@pytest.fixture
def ml_client(tmp_path, monkeypatch):
    from weeing_weeing.db import users
    from weeing_weeing.ml import interface

    monkeypatch.setattr(users, "SCRYPT_N", 2**10)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db.sqlite'}")
    monkeypatch.setenv("TELEMETRY_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setenv("ML_PREDICTION_DIR", str(tmp_path / "predictions"))
    monkeypatch.setenv("ML_PREDICTION_ENABLED", "true")
    path = tmp_path / "model.joblib"
    path.write_bytes(b"fake")
    monkeypatch.setenv("ML_MODEL_PATH", str(path))
    monkeypatch.setenv("ML_MODEL_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    predictor = FutureErrorPredictor(
        Model(),
        {
            "feature_names": FEATURE_NAMES,
            "model_version": "test-api",
            "warning_threshold": 0.3,
        },
    )
    monkeypatch.setattr(interface.FutureErrorPredictor, "load", lambda path: predictor)
    db.get_users().create_user(
        UserAccount(employee_no="A0001", name="테스트", role=Role.CONTROL),
        "fake-password",
    )
    with TestClient(app) as client:
        deadline = time.monotonic() + 3
        while not app.state.ml_service.loaded and time.monotonic() < deadline:
            time.sleep(0.005)
        assert app.state.ml_service.loaded
        response = client.post(
            "/auth/login", json={"employee_no": "A0001", "password": "fake-password"}
        )
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        yield client, headers


def test_authentication_read_only_and_limit(ml_client):
    client, headers = ml_client
    assert client.get("/ml/prediction").status_code == 401
    assert client.get("/ml/predictions").status_code == 401
    response = client.get("/ml/prediction", headers=headers)
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["prediction"]["status"] == "not_ready"
    assert client.get("/ml/predictions?limit=201", headers=headers).status_code == 422
    assert client.get("/ml/predictions", headers=headers).json()["items"] == []
    client.post("/auth/logout", headers=headers)
    assert client.get("/ml/prediction", headers=headers).status_code == 401


def test_real_websocket_dispatch_and_prediction_without_detector_change(
    ml_client, sample_rows
):
    from datetime import datetime, timedelta

    client, headers = ml_client
    source = TelemetryRecord.model_validate(sample_rows[0]).model_dump(mode="json")
    source.update(dc_input_current_a=0.2, motor_housing_temp_c=30)
    start = datetime.fromisoformat(source["timestamp"])
    with client.websocket_connect("/ws/telemetry") as socket:
        ready = socket.receive_json()
        for index in range(62):
            record = {
                **source,
                "record_id": f"ml-{index}",
                "timestamp": (start + timedelta(seconds=index / 2)).isoformat(),
            }
            socket.send_json(record)
            ack = socket.receive_json()
            assert ack["status"] == "processed"
            result = wait_result(client, headers, record["record_id"])
            assert result["run_id"] == ready["run_id"]
            if index < 60:
                assert result["prediction"]["status"] == "not_ready"
        assert result["prediction_usable"]
        probabilities = result["prediction"]["probabilities"]
        assert set(probabilities) == set(CLASSES)
        assert sum(probabilities.values()) == pytest.approx(1)
        assert result["prediction"]["inference_ms"] < 500
        assert (
            len(client.get("/ml/predictions?limit=3", headers=headers).json()["items"])
            == 3
        )
    assert not client.get("/ml/prediction", headers=headers).json()["prediction_usable"]


def test_ml_fault_cannot_change_detector_ack(ml_client, sample_rows, monkeypatch):
    client, _ = ml_client

    def fail(*args):
        raise RuntimeError("test failure")

    monkeypatch.setattr(app.state.ml_service, "submit", fail)
    row = TelemetryRecord.model_validate(sample_rows[0]).model_dump(mode="json")
    with client.websocket_connect("/ws/telemetry") as socket:
        socket.receive_json()
        socket.send_json(row)
        assert socket.receive_json()["status"] == "processed"
