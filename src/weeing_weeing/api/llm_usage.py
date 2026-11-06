"""LLM 사용량 요약 API(#207). 관리자·관제 담당자가 토큰·비용·호출 수를 간단히 본다.

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
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from weeing_weeing.api.auth import CurrentUser
from weeing_weeing.config import Settings, get_settings
from weeing_weeing.contracts import Role, UserAccount

router = APIRouter(tags=["llm-usage"])
logger = logging.getLogger(__name__)

METRICS_PATH = "/api/public/v2/metrics"

Period = Literal["1h", "24h", "7d", "30d", "all"]
Granularity = Literal["minute", "hour", "day", "month"]

# 누적(all)의 시작 시각. 이 프로젝트의 Langfuse 기록은 2026-10월부터라 그보다 이르면 충분하다.
ALL_TIME_START = datetime(2026, 1, 1, tzinfo=UTC)

# 기간별 길이(None=누적)와 추이 막대 하나의 단위. 막대가 수십 개 안쪽이 되게 고른다.
PERIODS: dict[str, tuple[timedelta | None, Granularity]] = {
    "1h": (timedelta(hours=1), "minute"),
    "24h": (timedelta(hours=24), "hour"),
    "7d": (timedelta(days=7), "day"),
    "30d": (timedelta(days=30), "day"),
    "all": (None, "month"),
}

# 화면 카드와 같은 규칙: 계정 관리자 또는 관제 담당자(프론트 canViewLlmUsage와 맞춘다).
USAGE_ROLES = frozenset({Role.CONTROL})


def can_view_usage(user: UserAccount) -> bool:
    return user.is_admin or user.role in USAGE_ROLES


def require_usage_viewer(user: CurrentUser) -> UserAccount:
    if not can_view_usage(user):
        raise HTTPException(
            status_code=403, detail="관리자 또는 관제 담당자만 볼 수 있습니다."
        )
    return user


UsageViewer = Annotated[UserAccount, Depends(require_usage_viewer)]


class ModelUsage(BaseModel):
    model: str
    calls: int = 0
    tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0


class SeriesPoint(BaseModel):
    time: datetime  # 막대 시작 시각(UTC)
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0


class LlmUsageSummary(BaseModel):
    status: Literal["ok", "not_configured", "failed"]
    message: str = ""
    period: Period
    granularity: Granularity
    from_time: datetime
    to_time: datetime
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0
    calls: int = 0  # 모델 이름이 있는 기록(LLM 호출)만 센다
    models: list[ModelUsage] = []
    series: list[SeriesPoint] = []
    dashboard_url: str = ""


def langfuse_http() -> Iterator[httpx.Client]:
    """테스트에서 가짜 전송(httpx.MockTransport)으로 바꿔 끼운다."""
    with httpx.Client() as client:
        yield client


Http = Annotated[httpx.Client, Depends(langfuse_http)]


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def metrics_query(start: datetime, end: datetime, granularity: Granularity) -> dict:
    return {
        "view": "observations",
        "metrics": [
            {"measure": "totalTokens", "aggregation": "sum"},
            {"measure": "inputTokens", "aggregation": "sum"},
            {"measure": "outputTokens", "aggregation": "sum"},
            {"measure": "totalCost", "aggregation": "sum"},
            {"measure": "count", "aggregation": "count"},
        ],
        "dimensions": [{"field": "providedModelName"}],
        "filters": [],
        "timeDimension": {"granularity": granularity},
        "fromTimestamp": _iso(start),
        "toTimestamp": _iso(end),
        "orderBy": [{"field": "time_dimension", "direction": "asc"}],
        "config": {"row_limit": 1000},
    }


def _number(value, kind):
    # ClickHouse 집계는 문자열이나 null로 올 수 있다.
    try:
        return kind(float(value or 0))
    except (TypeError, ValueError):
        return kind(0)


def bucket_start(value: datetime, granularity: Granularity) -> datetime:
    value = value.astimezone(UTC)
    if granularity == "minute":
        return value.replace(second=0, microsecond=0)
    if granularity == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    if granularity == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_bucket(value: datetime, granularity: Granularity) -> datetime:
    if granularity == "minute":
        return value + timedelta(minutes=1)
    if granularity == "hour":
        return value + timedelta(hours=1)
    if granularity == "day":
        return value + timedelta(days=1)
    year, month = divmod(value.month, 12)
    return value.replace(year=value.year + year, month=month + 1)


def _parse_time(raw) -> datetime | None:
    # Langfuse는 "2026-11-05T00:00:00.000Z" 또는 "2026-11-05 00:00:00" 꼴로 준다.
    text = str(raw or "").strip().replace(" ", "T").replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def empty_series(
    start: datetime, end: datetime, granularity: Granularity
) -> dict[datetime, SeriesPoint]:
    """기록이 없는 구간도 0 막대로 보이게 기간 전체의 빈 막대를 만든다."""
    series: dict[datetime, SeriesPoint] = {}
    cursor = bucket_start(start, granularity)
    while cursor < end:
        series[cursor] = SeriesPoint(time=cursor)
        cursor = _next_bucket(cursor, granularity)
    return series


def summarize(
    rows: list[dict], start: datetime, end: datetime, granularity: Granularity
) -> tuple[list[ModelUsage], list[SeriesPoint]]:
    """(시간, 모델) 행을 모델별·시간별로 합친다. 모델이 없는 행(span 등)은 뺀다."""
    models: dict[str, ModelUsage] = {}
    series = empty_series(start, end, granularity)
    for row in rows:
        model = str(row.get("providedModelName") or "").strip()
        if not model:
            continue
        calls = _number(row.get("count_count"), int)
        tokens = _number(row.get("sum_totalTokens"), int)
        cost = _number(row.get("sum_totalCost"), float)
        item = models.setdefault(model, ModelUsage(model=model))
        item.calls += calls
        item.tokens += tokens
        item.input_tokens += _number(row.get("sum_inputTokens"), int)
        item.output_tokens += _number(row.get("sum_outputTokens"), int)
        item.cost_usd += cost
        when = _parse_time(row.get("time_dimension"))
        if when is None:
            continue
        key = bucket_start(when, granularity)
        point = series.setdefault(key, SeriesPoint(time=key))
        point.calls += calls
        point.tokens += tokens
        point.cost_usd += cost
    ordered_models = sorted(models.values(), key=lambda m: m.cost_usd, reverse=True)
    ordered_series = [series[key] for key in sorted(series)]
    return ordered_models, ordered_series


def fetch_summary(
    settings: Settings, http: httpx.Client, period: Period, now: datetime
) -> LlmUsageSummary:
    length, granularity = PERIODS[period]
    end = now.astimezone(UTC)
    start = end - length if length else ALL_TIME_START
    base = LlmUsageSummary(
        status="ok",
        period=period,
        granularity=granularity,
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
            params={"query": json.dumps(metrics_query(start, end, granularity))},
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

    models, series = summarize(
        rows if isinstance(rows, list) else [], start, end, granularity
    )
    return base.model_copy(
        update={
            "models": models,
            "series": series,
            "total_tokens": sum(m.tokens for m in models),
            "input_tokens": sum(m.input_tokens for m in models),
            "output_tokens": sum(m.output_tokens for m in models),
            "total_cost_usd": sum(m.cost_usd for m in models),
            "calls": sum(m.calls for m in models),
        }
    )


def _failed(base: LlmUsageSummary, message: str) -> LlmUsageSummary:
    return base.model_copy(update={"status": "failed", "message": message})


@router.get("/llm-usage")
def llm_usage(
    _: UsageViewer,
    http: Http,
    period: Annotated[Period, Query()] = "7d",
) -> LlmUsageSummary:
    return fetch_summary(get_settings(), http, period, datetime.now(UTC))
