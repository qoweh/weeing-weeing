"""LLM 사용량 요약 API(#207): 관리자·관제 담당자 권한, 기간, 가짜 Langfuse 응답 집계, 실패 처리.

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
        "sum_inputTokens": "1000",
        "sum_outputTokens": "200",
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
        UserAccount(employee_no="C1101", name="박관제", role=Role.CONTROL), PASSWORD
    )
    repo.create_user(
        UserAccount(employee_no="L2101", name="최보전", role=Role.MAINT_LEAD), PASSWORD
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
    response = client.get("/llm-usage?period=30d", headers=login(client))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["period"] == "30d"
    assert body["granularity"] == "day"
    assert body["total_tokens"] == 2500
    assert body["input_tokens"] == 1000
    assert body["output_tokens"] == 200
    assert body["calls"] == 9
    assert body["total_cost_usd"] == pytest.approx(0.021)
    assert [m["model"] for m in body["models"]] == [
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ]
    assert body["models"][0]["tokens"] == 2000
    assert body["models"][0]["input_tokens"] == 1000
    assert body["dashboard_url"] == "https://langfuse.example.test/p"

    # 30일 기간 전체가 날짜 막대로 채워지고, 기록이 있는 날만 값이 있다.
    series = {point["time"][:10]: point for point in body["series"]}
    assert len(body["series"]) in (30, 31)
    assert series["2026-11-05"]["calls"] == 3
    assert series["2026-11-06"]["calls"] == 6
    assert sum(point["calls"] for point in body["series"]) == 9

    assert seen["path"] == "/api/public/v2/metrics"
    assert seen["auth"].startswith("Basic ")
    assert seen["query"]["view"] == "observations"
    assert seen["query"]["timeDimension"] == {"granularity": "day"}
    measures = {metric["measure"] for metric in seen["query"]["metrics"]}
    assert {"inputTokens", "outputTokens", "totalTokens", "totalCost"} <= measures


@pytest.mark.parametrize(
    ("period", "granularity", "points"),
    [("1h", "minute", (60, 61)), ("24h", "hour", (24, 25)), ("7d", "day", (7, 8))],
)
def test_period_sets_granularity_and_buckets(client, period, granularity, points):
    seen = {}

    def handler(request):
        seen["query"] = json.loads(request.url.params["query"])
        return httpx.Response(200, json={"data": []})

    fake_langfuse(handler)
    body = client.get(f"/llm-usage?period={period}", headers=login(client)).json()
    assert body["status"] == "ok"
    assert body["granularity"] == granularity
    assert seen["query"]["timeDimension"] == {"granularity": granularity}
    assert len(body["series"]) in points
    assert body["total_tokens"] == 0


def test_all_period_starts_at_fixed_date_by_month(client):
    seen = {}

    def handler(request):
        seen["query"] = json.loads(request.url.params["query"])
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        # 공백 구분 시각도 읽는다.
                        "time_dimension": "2026-10-01 00:00:00",
                        "providedModelName": "claude-haiku-5-5",
                        "sum_totalTokens": 10,
                        "sum_totalCost": 0.5,
                        "count_count": 1,
                    }
                ]
            },
        )

    fake_langfuse(handler)
    body = client.get("/llm-usage?period=all", headers=login(client)).json()
    assert seen["query"]["fromTimestamp"] == "2026-01-01T00:00:00Z"
    assert seen["query"]["timeDimension"] == {"granularity": "month"}
    assert body["series"][0]["time"].startswith("2026-01-01")
    october = [p for p in body["series"] if p["time"].startswith("2026-10-01")]
    assert october[0]["cost_usd"] == pytest.approx(0.5)


def test_control_role_can_view(client):
    fake_langfuse(lambda request: httpx.Response(200, json={"data": ROWS}))
    response = client.get("/llm-usage", headers=login(client, "C1101"))
    assert response.status_code == 200, response.text
    assert response.json()["calls"] == 9


@pytest.mark.parametrize("employee_no", ["E1001", "L2101"])
def test_other_roles_are_403(client, employee_no):
    fake_langfuse(lambda request: pytest.fail("권한 없는 요청이 Langfuse를 불렀다"))
    response = client.get("/llm-usage", headers=login(client, employee_no))
    assert response.status_code == 403


def test_login_required(client):
    assert client.get("/llm-usage").status_code == 401


def test_unknown_period_is_422(client):
    response = client.get("/llm-usage?period=90d", headers=login(client))
    assert response.status_code == 422


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
