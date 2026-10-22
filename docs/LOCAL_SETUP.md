# 로컬 개발 환경

목표: 처음 받은 사람이 10분 안에 테스트를 돌리고 API를 띄운다.

## 0. 필요한 도구

| 도구 | 용도 | 확인 |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python·패키지 관리 | `uv --version` |
| Git | 협업 | `git --version` |
| Docker Desktop | PostgreSQL (2차부터) | `docker compose version` |
| [Ollama](https://ollama.com) | 로컬 LLM (Agent 담당은 1차부터) | `ollama --version` |

uv 설치:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# 또는 Homebrew
brew install uv
```

## 1. 설치와 검사

```bash
git clone git@github.com:qoweh/weeing-weeing.git
cd weeing-weeing
uv sync --locked --no-install-project   # Python 3.12 자동 설치 + .venv 생성 + uv.lock 기준 설치
cp .env.example .env                    # 필요한 값만 채운다
uv run --no-sync pytest                 # 테스트
uv run --no-sync ruff check . && uv run --no-sync ruff format --check .
uv run --no-sync pre-commit install     # 커밋 전 자동 검사 (1회)
```

`make`가 있으면 위 명령을 `make setup`, `make check`로 줄여 쓸 수 있다(`make help`).

> 프로젝트 자체는 설치하지 않는 것이 팀 규칙이다(`--no-install-project`). 옵션 없이 `uv run`을 쓰면 실행 전에 프로젝트를 설치하므로 `uv run --no-sync`로 실행한다. 대신 의존성이 바뀌면 `make setup`(또는 위 `uv sync` 명령)을 다시 실행한다. 패키지 import는 `pytest`의 `pythonpath`와 `uvicorn --app-dir src`가 맡는다.

> ⚠️ `pip install` 대신 반드시 `uv add <패키지>`(개발용은 `uv add --dev`)를 쓴다. `pyproject.toml`과 `uv.lock`을 함께 커밋해야 팀원 환경이 같아진다. 다른 사람 변경을 pull 받은 뒤에는 `make setup`을 한 번 실행한다.

## 2. API 띄우기

```bash
uv run --no-sync --env-file .env uvicorn --app-dir src weeing_weeing.api.app:app --reload   # 또는 make api
```

http://localhost:8000/health 와 http://localhost:8000/docs 에서 확인한다.

## 3. PostgreSQL (2차부터)

```bash
docker compose up -d postgres     # 또는 make db-up
docker compose ps                 # postgres 가 healthy 인지 확인
```

접속 정보는 `.env`의 `DATABASE_URL`. 데이터는 docker 볼륨 `postgres_data`에 남는다.

## 4. Ollama

- **macOS**: Ollama 앱을 설치해 쓴다. 컨테이너 안에서는 GPU를 못 써서 느리다
- **Linux 서버**: `docker compose --profile ollama up -d ollama`
- 모델 받기: `ollama pull <모델명>` 후 `.env`의 `OLLAMA_MODEL`에 기입

## 문제가 생기면

| 증상 | 확인 |
|---|---|
| `uv sync --locked` 가 lock 불일치로 실패 | 누군가 `pyproject.toml`만 커밋한 경우. 그 PR에 `uv.lock` 반영을 요청한다. `--locked`를 빼서 우회하지 않는다 |
| `uv_build` 버전 경고 | 설치된 uv가 더 새 버전일 때 나오는 경고. 동작에는 영향 없음 |
| 5432 포트 사용 중 | 로컬에 이미 PostgreSQL이 떠 있음. 끄거나 compose 포트를 바꾼다 |
