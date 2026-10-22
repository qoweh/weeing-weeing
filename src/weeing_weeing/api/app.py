from fastapi import FastAPI

from weeing_weeing import __version__
from weeing_weeing.contracts import RULE_VERSION, SCHEMA_VERSION

app = FastAPI(title="weeing-weeing", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
    }
