# API(FastAPI) 운영 이미지. 빌드 위치는 레포 루트다(docs/DEPLOY.md).
#   docker build -f deploy/api.Dockerfile -t weeing-api .
# RAG 모델(약 4.5GB)은 이미지에 넣지 않고 /models 볼륨에 한 번 받는다(HF_HOME).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# 의존성 층을 소스와 분리한다. 코드만 바뀌면 이 층은 캐시를 쓴다.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY alembic.ini ./
COPY src ./src
COPY scripts ./scripts
COPY data ./data

# 볼륨으로 붙는 폴더를 미리 만들어 두면 새 볼륨이 이 소유자를 물려받는다.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/storage /app/outputs /models \
    && chown -R app:app /app/storage /app/outputs /models

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# Caddy가 /api 접두사를 떼고 넘기므로 root-path로 문서(/api/docs) 경로를 맞춘다.
# 분석 서비스·모델이 프로세스 안에 있으므로 워커는 1개로 둔다.
CMD ["uvicorn", "--app-dir", "src", "weeing_weeing.api.app:app", \
     "--host", "0.0.0.0", "--port", "8000", "--root-path", "/api", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
