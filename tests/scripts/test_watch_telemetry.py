import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

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


def snapshot(run_id="run-a", sequence=1):
    return {
        "epoch": "fake-epoch",
        "run_id": run_id,
        "sequence": sequence,
        "producer_connected": True,
        "stale": False,
        "telemetry": {"timestamp": "2026-11-04T00:00:00Z"},
        "received_at": "2026-11-04T00:00:00Z",
        "db_status": "saved",
        "agent_status": "not_connected",
        "context_preset": "RUN_ONLY",
        "incidents": [],
    }


def frame(state):
    return (
        "event: snapshot\ndata: "
        + json.dumps({"event": "snapshot", "state": state})
        + "\n\n"
    ).encode()


class StreamResponse(io.BytesIO):
    headers = {"Content-Type": "text/event-stream; charset=utf-8"}


def stream_monitor(body):
    monitor = watch.Monitor("https://example.invalid/api")
    monitor.token = "fake-session"
    calls = []
    responses = []

    class FakeOpener:
        def open(self, request, *, timeout):
            calls.append(request)
            assert timeout == 10
            if request.full_url.endswith("/telemetry/stream"):
                response = StreamResponse(body)
                responses.append(response)
                return response
            assert request.full_url.endswith("/auth/logout")
            return io.BytesIO(b"")

    monitor.opener = FakeOpener()
    return monitor, calls, responses


def test_sse_parser_supports_bom_comments_crlf_and_multiline_data():
    body = (
        "\ufeff: heartbeat\r\nid: ignored\r\nevent: snapshot\r\n"
        'data: {"event":"snapshot",\r\ndata: "state":{"label":"정상"}}\r\n\r\n'
    ).encode()
    events = watch.sse_events(io.BytesIO(body))
    assert next(events) == (
        "snapshot",
        {"event": "snapshot", "state": {"label": "정상"}},
    )


def test_stream_uses_bearer_header_and_closes_on_limit():
    monitor, calls, responses = stream_monitor(frame(snapshot()))
    states = monitor.stream()
    assert next(states) == snapshot()
    states.close()
    assert responses[0].closed
    assert calls[0].full_url == "https://example.invalid/api/telemetry/stream"
    assert calls[0].get_header("Accept") == "text/event-stream"
    assert calls[0].get_header("Authorization") == "Bearer fake-session"
    assert calls[0].get_method() == "GET"


@pytest.mark.parametrize("status_code", [401, 403, 503])
def test_stream_error_event_stops_and_closes_without_exposing_message(status_code):
    body = (
        "event: error\ndata: "
        + json.dumps({"status_code": status_code, "message": "private-response-body"})
        + "\n\n"
    ).encode()
    monitor, _, responses = stream_monitor(body)
    with pytest.raises(watch.StreamError) as caught:
        next(monitor.stream())
    assert caught.value.status_code == status_code
    assert "private-response-body" not in str(caught.value)
    assert responses[0].closed


@pytest.mark.parametrize(
    "body",
    [
        b"event: snapshot\ndata: []\n\n",
        b'event: snapshot\ndata: {"event":"snapshot","state":null}\n\n',
        b'event: snapshot\ndata: {"event":"other","state":{}}\n\n',
        b'event: error\ndata: {"status_code":"401"}\n\n',
        b'event: error\ndata: {"status_code":true}\n\n',
        b'event: error\ndata: {"status_code":200}\n\n',
    ],
)
def test_stream_rejects_malformed_events(body):
    monitor, _, responses = stream_monitor(body)
    with pytest.raises(ValueError):
        next(monitor.stream())
    assert responses[0].closed


@pytest.mark.parametrize("body", [b"", b'event: snapshot\ndata: {"state":{}}\n'])
def test_stream_eof_is_failure_not_a_successful_empty_subscription(body):
    monitor, _, responses = stream_monitor(body)
    with pytest.raises(watch.StreamError):
        next(monitor.stream())
    assert responses[0].closed


@pytest.mark.parametrize(
    "body",
    [b"data: " + b"x" * 65_536 + b"\n", (b":" + b"x" * 63_999 + b"\n") * 16],
    ids=["oversized-line", "oversized-frame"],
)
def test_sse_parser_bounds_lines_and_total_frame_bytes(body):
    with pytest.raises(ValueError):
        next(watch.sse_events(io.BytesIO(body)))


def test_stream_rejects_non_sse_content_type():
    monitor, _, responses = stream_monitor(frame(snapshot()))
    original_open = monitor.opener.open

    def wrong_content_type(*args, **kwargs):
        response = original_open(*args, **kwargs)
        response.headers = {"Content-Type": "application/json"}
        return response

    monitor.opener.open = wrong_content_type
    with pytest.raises(ValueError):
        next(monitor.stream())
    assert responses[0].closed


def run_monitor_cli(monkeypatch, monitor, arguments, *, mode="--stream"):
    monkeypatch.setattr(watch.sys, "argv", ["watch_telemetry.py", mode, *arguments])
    monkeypatch.setattr(watch.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: "A0001")
    monkeypatch.setattr(watch.getpass, "getpass", lambda _: "fake-password")
    monkeypatch.setattr(monitor, "login", lambda *_: None)
    monkeypatch.setattr(watch, "Monitor", lambda _: monitor)
    return watch.main()


def test_stream_cli_counts_snapshots_detects_new_run_and_logs_out(monkeypatch, capsys):
    monitor, calls, responses = stream_monitor(
        frame(snapshot()) + frame(snapshot("run-b", 2))
    )
    assert run_monitor_cli(monkeypatch, monitor, ["--max-events", "2"]) == 0
    output = capsys.readouterr().out
    assert "SSE snapshot #2" in output
    assert "새 프로세스/감지 세션" in output
    assert "SSE 스냅샷 2개 수신 완료" in output
    assert "fake-session" not in output
    assert responses[0].closed
    assert [call.full_url.rsplit("/", 1)[-1] for call in calls] == ["stream", "logout"]
    assert monitor.token == ""


def test_stream_cli_once_closes_before_reading_next_event(monkeypatch, capsys):
    monitor, _, responses = stream_monitor(frame(snapshot()) + b"invalid next frame")
    assert run_monitor_cli(monkeypatch, monitor, ["--once"]) == 0
    assert "SSE 스냅샷 1개 수신 완료" in capsys.readouterr().out
    assert responses[0].closed


def test_stream_cli_expiry_requests_relogin_and_logs_out(monkeypatch, capsys):
    monitor, calls, responses = stream_monitor(
        frame(snapshot())
        + b'event: error\ndata: {"status_code":401,"message":"private-body"}\n\n'
    )
    assert run_monitor_cli(monkeypatch, monitor, []) == 1
    output = capsys.readouterr().out
    assert "SSE 인증 종료 HTTP 401" in output
    assert "private-body" not in output
    assert responses[0].closed
    assert calls[-1].full_url.endswith("/auth/logout")


@pytest.mark.parametrize("arguments", [["0"], ["-1"], ["1", "--once"]])
def test_invalid_stream_limit_is_rejected_before_login(monkeypatch, arguments):
    monkeypatch.setattr(
        watch.sys,
        "argv",
        ["watch_telemetry.py", "--stream", "--max-events", *arguments],
    )
    with pytest.raises(SystemExit) as caught:
        watch.main()
    assert caught.value.code == 2


def test_revocation_logs_out_only_after_first_snapshot_and_observes_401():
    monitor, calls, responses = stream_monitor(
        frame(snapshot())
        + frame(snapshot(sequence=2))
        + b'event: error\ndata: {"status_code":401}\n\n'
    )
    result = watch.verify_revocation(monitor)
    assert result["status_code"] == 401
    assert result["discarded_snapshots"] == 1
    assert result["run_id"] == "run-a"
    assert monitor.token == ""
    assert [call.full_url.rsplit("/", 1)[-1] for call in calls] == ["stream", "logout"]
    assert calls[0].get_header("Authorization") == "Bearer fake-session"
    assert calls[1].get_header("Authorization") == "Bearer fake-session"
    assert responses[0].closed


def test_revocation_rejects_401_before_any_snapshot():
    monitor, calls, responses = stream_monitor(
        b'event: error\ndata: {"status_code":401}\n\n'
    )
    with pytest.raises(watch.StreamError):
        watch.verify_revocation(monitor)
    assert len(calls) == 1
    assert responses[0].closed


@pytest.mark.parametrize(
    "suffix",
    [
        b"",
        b'event: error\ndata: {"status_code":403}\n\n',
        b'event: error\ndata: {"status_code":503}\n\n',
    ],
    ids=["eof", "unexpected-403", "server-503"],
)
def test_revocation_does_not_pass_on_eof_or_unexpected_server_error(suffix):
    monitor, _, responses = stream_monitor(frame(snapshot()) + suffix)
    with pytest.raises(watch.StreamError):
        watch.verify_revocation(monitor)
    assert responses[0].closed


def test_revocation_does_not_pass_when_logout_fails(monkeypatch):
    from urllib.error import HTTPError

    monitor, _, responses = stream_monitor(
        frame(snapshot()) + b'event: error\ndata: {"status_code":401}\n\n'
    )

    def failed_logout(*args, **kwargs):
        raise HTTPError("https://example.invalid/api/auth/logout", 503, "", {}, None)

    monkeypatch.setattr(monitor, "request", failed_logout)
    with pytest.raises(HTTPError):
        watch.verify_revocation(monitor)
    assert responses[0].closed


@pytest.mark.parametrize("late_error", [False, True])
def test_revocation_has_a_deadline_even_if_snapshots_continue(monkeypatch, late_error):
    clock = [0]
    closed = []
    monkeypatch.setattr(watch.time, "monotonic", lambda: clock[0])

    class FakeMonitor:
        def stream(self):
            try:
                yield snapshot()
                if late_error:
                    clock[0] = 4
                    raise watch.StreamError(401)
                while True:
                    clock[0] += 1
                    yield snapshot(sequence=clock[0])
            finally:
                closed.append(True)

        def logout(self):
            pass

    with pytest.raises(watch.RevocationTimeoutError):
        watch.verify_revocation(FakeMonitor(), max_wait=3)
    assert closed == [True]


def test_revocation_cli_reports_expected_401_as_success(monkeypatch, capsys):
    monitor, calls, responses = stream_monitor(
        frame(snapshot()) + b'event: error\ndata: {"status_code":401}\n\n'
    )
    assert run_monitor_cli(monkeypatch, monitor, [], mode="--verify-revocation") == 0
    output = capsys.readouterr().out
    assert "RESULT: PASS_SSE_SESSION_REVOCATION" in output
    assert "로그아웃 확인 실패" not in output
    assert "fake-session" not in output
    assert len(calls) == 2
    assert responses[0].closed


def test_revocation_cli_does_not_report_initial_auth_denial_as_success(
    monkeypatch, capsys
):
    monitor, _, responses = stream_monitor(
        b'event: error\ndata: {"status_code":401}\n\n'
    )
    assert run_monitor_cli(monkeypatch, monitor, [], mode="--verify-revocation") == 1
    assert "PASS_SSE_SESSION_REVOCATION" not in capsys.readouterr().out
    assert responses[0].closed


@pytest.mark.parametrize("options", [["--stream"], ["--once"], ["--max-events", "1"]])
def test_revocation_cannot_be_combined_with_other_modes(monkeypatch, options):
    monkeypatch.setattr(
        watch.sys, "argv", ["watch_telemetry.py", "--verify-revocation", *options]
    )
    with pytest.raises(SystemExit) as caught:
        watch.main()
    assert caught.value.code == 2
