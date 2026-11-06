"""LLM 사용량 요약 API(#207): 관리자 권한, 가짜 Langfuse 응답 집계, 실패 처리.

실제 Langfuse에는 연결하지 않는다(httpx.MockTransport).
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from weeing_weeing.api.app import app
from weeing_weeing.api.llm_usage import langfuse_http
from weeing_weeing.contracts import Role, UserAccount
from weeing_weeing.db import interface as db

PASSWORD = "correct-horse-1"
ROWS = [
    {
        "time_dimension": "2026-11-05T00:00:00.000Z",
        "providedModelName": "claude-sonnet-5-5",
        "sum_totalTokens": "1200",
        "sum_totalCost": "0.012",
        "count_count": "3",
    },
    {
        "time_dimension": "2026-11-06T00:00:00.000Z",
        "providedModelName": "claude-sonnet-5-5",
        "sum_totalTokens": 800,
        "sum_totalCost": 0.008,
        "count_count": 2,
    },
    {
        "time_dimension": "2026-11-06T00:00:00.000Z",
        "providedModelName": "claude-haiku-5-5",
        "sum_totalTokens": 500,
        "sum_totalCost": 0.001,
        "count_count": 4,
    },
    # 모델이 없는 span 행은 호출 수에 넣지 않는다.
    {
        "time_dimension": "2026-11-06T00:00:00.000Z",
        "providedModelName": None,
        "sum_totalTokens": 0,
        "sum_totalCost": None,
        "count_count": 9,
    },
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from weeing_weeing.db import users as module

    monkeypatch.setattr(module, "SCRYPT_N", 2**10)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'usage.db'}")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-fake")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-fake")
    monkeypatch.setenv("LANGFUSE_DASHBOARD_URL", "https://langfuse.example.test/p")
    repo = db.get_users()
    repo.create_user(
        UserAccount(
            employee_no="A0001", name="관리자", role=Role.CONTROL, is_admin=True
        ),
        PASSWORD,
    )
    repo.create_user(
        UserAccount(employee_no="E1001", name="김점검", role=Role.INSPECTOR), PASSWORD
    )
    yield TestClient(app)
    app.dependency_overrides.pop(langfuse_http, None)


def login(client, employee_no="A0001") -> dict:
    response = client.post(
        "/auth/login", json={"employee_no": employee_no, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def fake_langfuse(handler):
    def override():
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            yield http

    app.dependency_overrides[langfuse_http] = override


def test_admin_sees_aggregated_usage(client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization", "")
        seen["query"] = json.loads(request.url.params["query"])
        return httpx.Response(200, json={"data": ROWS})

    fake_langfuse(handler)
    response = client.get("/llm-usage?days=30", headers=login(client))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["days"] == 30
    assert body["total_tokens"] == 2500
    assert body["calls"] == 9
    assert body["total_cost_usd"] == pytest.approx(0.021)
    assert [m["model"] for m in body["models"]] == [
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ]
    assert body["models"][0]["tokens"] == 2000
    assert [d["date"] for d in body["daily"]] == ["2026-11-05", "2026-11-06"]
    assert body["daily"][1]["calls"] == 6
    assert body["dashboard_url"] == "https://langfuse.example.test/p"

    assert seen["path"] == "/api/public/v2/metrics"
    assert seen["auth"].startswith("Basic ")
    assert seen["query"]["view"] == "observations"
    assert seen["query"]["timeDimension"] == {"granularity": "day"}


def test_non_admin_is_403(client):
    fake_langfuse(lambda request: pytest.fail("권한 없는 요청이 Langfuse를 불렀다"))
    response = client.get("/llm-usage", headers=login(client, "E1001"))
    assert response.status_code == 403


def test_login_required(client):
    assert client.get("/llm-usage").status_code == 401


def test_days_out_of_range_is_422(client):
    assert client.get("/llm-usage?days=31", headers=login(client)).status_code == 422


def test_timeout_reports_failed(client):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    fake_langfuse(handler)
    body = client.get("/llm-usage", headers=login(client)).json()
    assert body["status"] == "failed"
    assert "늦어" in body["message"]
    assert body["dashboard_url"] == "https://langfuse.example.test/p"


def test_http_error_reports_status_without_key(client):
    fake_langfuse(lambda request: httpx.Response(401, json={"message": "bad"}))
    body = client.get("/llm-usage", headers=login(client)).json()
    assert body["status"] == "failed"
    assert "401" in body["message"]
    assert "sk-lf-fake" not in json.dumps(body)


def test_not_configured_skips_call(client, monkeypatch):
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    fake_langfuse(lambda request: pytest.fail("설정이 없는데 Langfuse를 불렀다"))
    body = client.get("/llm-usage", headers=login(client)).json()
    assert body["status"] == "not_configured"
    assert body["total_tokens"] == 0
