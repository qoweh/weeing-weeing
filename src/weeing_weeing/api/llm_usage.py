"""LLM 사용량 요약 API(#207). 관리자만 토큰·비용·호출 수를 간단히 본다.

앱이 기록에 쓰는 Langfuse 키(LANGFUSE_PUBLIC_KEY·SECRET_KEY)로 Metrics API v2를 읽는다.
키가 속한 Langfuse 프로젝트 하나의 집계다. 자세한 분석은 LANGFUSE_DASHBOARD_URL 링크로 넘긴다.
Langfuse가 꺼져 있거나 느려도 화면이 깨지지 않게, 실패는 200 + status로 돌려준다.
"""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from weeing_weeing.api.auth import Admin
from weeing_weeing.config import Settings, get_settings

router = APIRouter(tags=["llm-usage"])
logger = logging.getLogger(__name__)

METRICS_PATH = "/api/public/v2/metrics"


class ModelUsage(BaseModel):
    model: str
    tokens: int
    cost_usd: float
    calls: int


class DailyUsage(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    tokens: int
    cost_usd: float
    calls: int


class LlmUsageSummary(BaseModel):
    status: Literal["ok", "not_configured", "failed"]
    message: str = ""
    days: int
    from_time: datetime
    to_time: datetime
    total_tokens: int = 0
    total_cost_usd: float = 0
    calls: int = 0  # 모델 이름이 있는 기록(LLM 호출)만 센다
    models: list[ModelUsage] = []
    daily: list[DailyUsage] = []
    dashboard_url: str = ""


def langfuse_http() -> Iterator[httpx.Client]:
    """테스트에서 가짜 전송(httpx.MockTransport)으로 바꿔 끼운다."""
    with httpx.Client() as client:
        yield client


Http = Annotated[httpx.Client, Depends(langfuse_http)]


def metrics_query(start: datetime, end: datetime) -> dict:
    return {
        "view": "observations",
        "metrics": [
            {"measure": "totalTokens", "aggregation": "sum"},
            {"measure": "totalCost", "aggregation": "sum"},
            {"measure": "count", "aggregation": "count"},
        ],
        "dimensions": [{"field": "providedModelName"}],
        "filters": [],
        "timeDimension": {"granularity": "day"},
        "fromTimestamp": start.isoformat().replace("+00:00", "Z"),
        "toTimestamp": end.isoformat().replace("+00:00", "Z"),
        "orderBy": [{"field": "time_dimension", "direction": "asc"}],
        "config": {"row_limit": 1000},
    }


def _number(value, kind):
    # ClickHouse 집계는 문자열이나 null로 올 수 있다.
    try:
        return kind(float(value or 0))
    except (TypeError, ValueError):
        return kind(0)


def summarize(rows: list[dict]) -> tuple[list[ModelUsage], list[DailyUsage]]:
    """(날짜, 모델) 행을 모델별·일별로 합친다. 모델이 없는 행(span 등)은 뺀다."""
    models: dict[str, ModelUsage] = {}
    daily: dict[str, DailyUsage] = {}
    for row in rows:
        model = str(row.get("providedModelName") or "").strip()
        if not model:
            continue
        tokens = _number(row.get("sum_totalTokens"), int)
        cost = _number(row.get("sum_totalCost"), float)
        calls = _number(row.get("count_count"), int)
        day = str(row.get("time_dimension") or "")[:10]
        for bucket, key, make in (
            (
                models,
                model,
                lambda: ModelUsage(model=model, tokens=0, cost_usd=0, calls=0),
            ),
            (daily, day, lambda: DailyUsage(date=day, tokens=0, cost_usd=0, calls=0)),
        ):
            item = bucket.setdefault(key, make())
            item.tokens += tokens
            item.cost_usd += cost
            item.calls += calls
    ordered_models = sorted(models.values(), key=lambda m: m.cost_usd, reverse=True)
    ordered_daily = sorted(daily.values(), key=lambda d: d.date)
    return ordered_models, ordered_daily


def fetch_summary(
    settings: Settings, http: httpx.Client, days: int, now: datetime
) -> LlmUsageSummary:
    end = now.astimezone(UTC)
    start = end - timedelta(days=days)
    base = LlmUsageSummary(
        status="ok",
        days=days,
        from_time=start,
        to_time=end,
        dashboard_url=settings.langfuse_dashboard_url,
    )
    if not (
        settings.langfuse_base_url
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    ):
        return base.model_copy(
            update={
                "status": "not_configured",
                "message": "Langfuse 주소 또는 키가 설정되지 않았습니다.",
            }
        )
    url = settings.langfuse_base_url.rstrip("/") + METRICS_PATH
    try:
        response = http.get(
            url,
            params={"query": json.dumps(metrics_query(start, end))},
            auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
            timeout=settings.langfuse_query_timeout_s,
        )
        response.raise_for_status()
        rows = response.json().get("data") or []
    except httpx.TimeoutException:
        logger.warning("Langfuse 사용량 조회 시간 초과")
        return _failed(base, "Langfuse 응답이 늦어 사용량을 불러오지 못했습니다.")
    except httpx.HTTPStatusError as exc:
        # 키 값이 들어가지 않도록 상태 코드만 남긴다.
        logger.warning("Langfuse 사용량 조회 실패: HTTP %s", exc.response.status_code)
        return _failed(
            base, f"Langfuse가 오류를 돌려줬습니다(HTTP {exc.response.status_code})."
        )
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning("Langfuse 사용량 조회 실패: %s", type(exc).__name__)
        return _failed(base, "Langfuse에 연결하지 못했습니다.")

    models, daily = summarize(rows if isinstance(rows, list) else [])
    return base.model_copy(
        update={
            "models": models,
            "daily": daily,
            "total_tokens": sum(m.tokens for m in models),
            "total_cost_usd": sum(m.cost_usd for m in models),
            "calls": sum(m.calls for m in models),
        }
    )


def _failed(base: LlmUsageSummary, message: str) -> LlmUsageSummary:
    return base.model_copy(update={"status": "failed", "message": message})


@router.get("/llm-usage")
def llm_usage(
    _: Admin,
    http: Http,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> LlmUsageSummary:
    return fetch_summary(get_settings(), http, days, datetime.now(UTC))
