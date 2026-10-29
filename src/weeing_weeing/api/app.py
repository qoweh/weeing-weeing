import logging
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from weeing_weeing import __version__
from weeing_weeing.api.analysis import AnalysisService
from weeing_weeing.api.analysis import router as analysis_router
from weeing_weeing.api.auth import router as auth_router
from weeing_weeing.api.documents import router as documents_router
from weeing_weeing.api.reports import router as reports_router
from weeing_weeing.api.telemetry import router as telemetry_router
from weeing_weeing.config import get_settings
from weeing_weeing.contracts import RULE_VERSION, SCHEMA_VERSION
from weeing_weeing.db.interface import DatabaseUnavailableError


@asynccontextmanager
async def lifespan(app):
    service = AnalysisService() if get_settings().analysis_auto_enabled else None
    app.state.analysis_service = service
    if service:
        service.start()
    else:
        logging.getLogger("uvicorn.error.analysis").info(
            "[분석 비활성] ANALYSIS_AUTO_ENABLED=true로 자동 호출 활성화(비용 발생)"
        )
    try:
        yield
    finally:
        if service:
            await anyio.to_thread.run_sync(service.stop)


app = FastAPI(title="weeing-weeing", version=__version__, lifespan=lifespan)
app.include_router(analysis_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(telemetry_router)
app.include_router(reports_router)


@app.exception_handler(DatabaseUnavailableError)
def _db_unavailable(_: Request, exc: DatabaseUnavailableError) -> JSONResponse:
    """라우터가 따로 잡지 않은 DB 연결 실패·잠금 대기 초과는 503으로 돌려준다."""
    return JSONResponse(
        status_code=503,
        content={"detail": "DB에 연결하지 못했습니다. 잠시 후 다시 시도하세요."},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
    }
