from fastapi import FastAPI

from weeing_weeing import __version__
from weeing_weeing.api.documents import router as documents_router
from weeing_weeing.api.telemetry import router as telemetry_router
from weeing_weeing.contracts import RULE_VERSION, SCHEMA_VERSION

app = FastAPI(title="weeing-weeing", version=__version__)
app.include_router(documents_router)
app.include_router(telemetry_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
    }
