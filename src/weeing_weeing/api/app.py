import logging
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from weeing_weeing import __version__
from weeing_weeing.api.analysis import AnalysisService
from weeing_weeing.api.analysis import router as analysis_router
from weeing_weeing.api.auth import router as auth_router
from weeing_weeing.api.chat import router as chat_router
from weeing_weeing.api.documents import router as documents_router
from weeing_weeing.api.llm_usage import router as llm_usage_router
from weeing_weeing.api.ml import router as ml_router
from weeing_weeing.api.reports import router as reports_router
from weeing_weeing.api.retention import RetentionWorker
from weeing_weeing.api.telemetry import router as telemetry_router
from weeing_weeing.api.telemetry_live import router as telemetry_live_router
from weeing_weeing.config import get_settings
from weeing_weeing.contracts import RULE_VERSION, SCHEMA_VERSION
from weeing_weeing.db.interface import DatabaseUnavailableError
from weeing_weeing.ml.interface import create_live_service


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    retention = (
        RetentionWorker(settings.database_url, settings.db_timeout_s)
        if settings.telemetry_retention_enabled
        else None
    )
    if retention:
        retention.start()
    service = (
        AnalysisService(analysis_enabled=settings.analysis_auto_enabled)
        if settings.analysis_auto_enabled or settings.telemetry_db_enabled
        else None
    )
    app.state.ml_service = create_live_service(
        enabled=settings.ml_prediction_enabled,
        model_path=settings.ml_model_path,
        model_sha256=settings.ml_model_sha256,
        output_dir=settings.ml_prediction_dir,
    ).start()
    app.state.analysis_service = service
    if service and service.analysis_enabled:
        service.start()
    else:
        logging.getLogger("uvicorn.error.analysis").info(
            "[분석 비활성] ANALYSIS_AUTO_ENABLED=true로 자동 호출 활성화(비용 발생)"
        )
        if service:
            logging.getLogger("uvicorn.error.analysis").info(
                "[DB 저장 활성] 센서·사건만 저장; 분석 작업 등록·호출 없음"
            )
    try:
        yield
    finally:
        await anyio.to_thread.run_sync(app.state.ml_service.stop)
        if service:
            await anyio.to_thread.run_sync(service.stop)
        if retention:
            await anyio.to_thread.run_sync(retention.stop)


app = FastAPI(title="weeing-weeing", version=__version__, lifespan=lifespan)
app.include_router(analysis_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(llm_usage_router)
app.include_router(telemetry_router)
app.include_router(telemetry_live_router)
app.include_router(ml_router)
app.include_router(reports_router)


@app.exception_handler(DatabaseUnavailableError)
def _db_unavailable(_: Request, exc: DatabaseUnavailableError) -> JSONResponse:
    """라우터가 따로 잡지 않은 DB 연결 실패·잠금 대기 초과는 503으로 돌려준다."""
    return JSONResponse(
        status_code=503,
        content={"detail": "DB에 연결하지 못했습니다. 잠시 후 다시 시도하세요."},
    )


@app.get("/health")
def health():
    service = getattr(app.state, "ml_service", None)
    model_ready = service is None or not service.enabled or service.loaded
    result = {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "ml_prediction": "disabled"
        if service is None or not service.enabled
        else "ready"
        if service.loaded
        else "unavailable",
    }
    if not model_ready:
        return JSONResponse(status_code=503, content={**result, "status": "degraded"})
    return result
