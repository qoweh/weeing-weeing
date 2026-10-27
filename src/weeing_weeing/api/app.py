from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from weeing_weeing import __version__
from weeing_weeing.api.auth import router as auth_router
from weeing_weeing.api.documents import router as documents_router
from weeing_weeing.api.telemetry import router as telemetry_router
from weeing_weeing.contracts import RULE_VERSION, SCHEMA_VERSION
from weeing_weeing.db.interface import DatabaseUnavailableError

app = FastAPI(title="weeing-weeing", version=__version__)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(telemetry_router)


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
