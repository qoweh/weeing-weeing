import importlib.util
import io
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "watch_telemetry",
    Path(__file__).resolve().parents[2] / "scripts/watch_telemetry.py",
)
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/api",
        "https://user:password@example.com/api",
        "https://example.com/api?token=bad",
        "file:///tmp/example",
    ],
)
def test_credentials_only_go_to_https_or_loopback(url):
    with pytest.raises(ValueError):
        watch.Monitor(url)


def test_monitor_login_read_logout_never_requests_analysis():
    monitor = watch.Monitor("http://127.0.0.1:8000")
    calls = []

    class FakeOpener:
        def open(self, request, *, timeout):
            calls.append(request)
            assert timeout == 10
            if request.full_url.endswith("/auth/login"):
                assert json.loads(request.data)["password"] == "fake-password"
                return io.BytesIO(b'{"access_token":"fake-session"}')
            assert request.get_header("Authorization") == "Bearer fake-session"
            return io.BytesIO(b"{}")

    monitor.opener = FakeOpener()
    monitor.login("A0001", "fake-password")
    monitor.request("/telemetry/latest")
    monitor.logout()
    assert monitor.token == ""
    assert [request.get_method() for request in calls] == ["POST", "GET", "POST"]
    assert not any("analysis" in request.full_url for request in calls)


def test_redirect_is_refused():
    assert (
        watch.NoRedirect().redirect_request(
            None, None, 302, "", {}, "https://other.invalid"
        )
        is None
    )


def test_disconnected_snapshot_is_not_rendered_as_healthy():
    text = watch.render(
        {
            "producer_connected": False,
            "stale": True,
            "run_id": "run-a",
            "sequence": 2,
            "telemetry": {"rpm": 100, "motor_housing_temp_c": None},
            "received_at": None,
            "db_status": "failed",
            "agent_status": "storage_failed",
            "context_preset": "NONE",
            "incidents": [],
        }
    )
    assert "송신 연결 없음" in text
    assert "현재 정상 상태를 보장하지 않습니다" in text
    assert "DB=failed" in text
    assert "motor_housing_temp_c: 결측/미수신" in text
