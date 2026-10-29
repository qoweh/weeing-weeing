# 로컬 개발 환경

목표: 처음 받은 사람이 10분 안에 테스트를 돌리고 API를 띄운다.

## 0. 필요한 도구

| 도구 | 용도 | 확인 |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python·패키지 관리 | `uv --version` |
| Git | 협업 | `git --version` |
| Docker Desktop | PostgreSQL (2차부터), Qdrant 서버 모드(선택) | `docker compose version` |
| Claude API 키 | 에이전트·LLM 점검(Agent·챗봇 담당) | `.env`의 `ANTHROPIC_API_KEY` |

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

## 3. DB (PostgreSQL)

문서 목록(`document` 테이블)이 DB에 있어서 `make index`와 업로드 API에 DB가 필요하다. 테이블과 사용법은 [DB.md](DB.md). 로그인할 시연 계정은 `make seed-users`([AUTH.md](AUTH.md)).

```bash
docker compose up -d postgres     # 또는 make db-up
docker compose ps                 # postgres 가 healthy 인지 확인
```

접속 정보는 `.env`의 `DATABASE_URL`. 데이터는 docker 볼륨 `postgres_data`에 남는다. 스키마는 `make index`·API가 시작할 때 최신으로 올린다(직접 올리려면 `make db-migrate`).

**Docker 없이 개발할 때**: `.env`에 `DATABASE_URL=sqlite:///storage/dev.db`. 같은 코드가 파일 하나(`storage/dev.db`, git 밖)로 동작한다. 지우면 처음 상태로 돌아가고, 다음 `make index`가 카탈로그 문서를 다시 넣는다(업로드 기록은 사라진다). 통합 시험·시연은 PostgreSQL로 한다.

DB 테스트는 SQLite로 항상 돌고, PostgreSQL에서도 확인하려면:
```bash
make db-up
TEST_DATABASE_URL=postgresql://weeing:weeing@localhost:5432/weeing uv run --no-sync pytest tests/db
```
테스트는 모든 테이블을 비우므로 실제 데이터가 있는 DB를 가리키지 않는다(CI는 별도 DB `weeing_test`).

## 4. LLM (Claude API)

로컬 LLM(Ollama)은 쓰지 않는다(2026-10-29 폐지, [DIRECTION_CHANGES](DIRECTION_CHANGES.md)). 받을 모델이 없고 API 키만 있으면 된다.

- 키: `.env`의 `# ANTHROPIC_API_KEY=` 주석을 풀고 넣는다. 줄이 없으면 `ant auth login` 프로필을 쓴다(빈 값으로 두면 프로필보다 우선해 인증이 실패한다). 키는 커밋하지 않고 로그·이슈에 붙이지 않는다
- 모델·깊이: `LLM_MODEL`(기본 `claude-opus-5-5`), `LLM_EFFORT`(기본 `medium`). 테스트(`make check`)는 가짜 클라이언트라 키 없이 돈다
- 확인: `make llm-check`. 근거를 고정한 사례 4개로 JSON 스키마·인용 규칙을 지키는지 점검한다(종료 코드 0 통과·1 실패 사례 있음·2 키·모델 문제). 사례마다 API를 한 번 부르므로 비용이 든다
- 모델 비교: `make llm-check ARGS="--model claude-sonnet-5-5 --repeat 3"`, `ARGS="--effort low"`. 보고서는 `outputs/llm_check/`
- 에이전트 실행: 색인(5절)을 마친 뒤 `make analyze`. 예시 사건(`data/eval/incident_p03_demo.json`)을 분석해 결과 JSON과 도구 호출 기록을 보여 준다
- 외부로 나가는 데이터: 사건 정보와 검색된 문서 조각만. 사번·결재 정보는 보내지 않는다([AGENT](AGENT.md))

## 5. RAG 색인 (벡터 DB)

문서 목록은 DB `document` 테이블이 원본이다(3절). 기준 문서는 `data/catalog.toml`(git)에 적으면 `make index`가 DB에 반영(seed)하고, 화면에서 올린 문서는 원본 PDF가 `storage/uploads/`(git 밖)에, 상태는 DB에 쌓인다. 처음 한 번 `make models`로 임베딩(`BAAI/bge-m3`)·리랭커(`BAAI/bge-reranker-v2-m3`) 모델을 받고(`.env.example` 기본값, 검색 중에는 내려받지 않는다), `make index`를 실행하면 DB 목록 전체를 색인한다. 리랭커를 끄려면 `.env`에 `RERANKER_MODEL=`(빈 값)(사용법: [scripts/README](../scripts/README.md)). 업로드 API(`POST /documents`)도 같은 Indexer·저장소를 쓴다.

| | Qdrant 로컬 모드 (기본) | Qdrant 서버 모드 |
|---|---|---|
| 설정 | `QDRANT_URL` 비움, `QDRANT_PATH=storage/qdrant` | `QDRANT_URL=http://localhost:6333` |
| 준비 | 없음 | `make qdrant-up` (= `docker compose --profile qdrant up -d qdrant`) |
| 정체 | qdrant-client 안의 파이썬 재구현, 폴더에 저장 | 실제 Qdrant 엔진. 대시보드 http://localhost:6333/dashboard |
| 동시 접근 | **한 폴더를 한 프로세스만** 연다 | 여러 프로세스 가능 |
| 용도 | 개발·단위 테스트 | 통합 시험·시연·운영 |

- **한 프로세스만 쓰기**: Qdrant 로컬 모드는 폴더를 한 프로세스만 열 수 있다. API 서버가 떠 있는 동안 `make index`를 실행하면 "다른 프로세스가 사용 중" 오류로 멈춘다(종료 코드 2). API를 끄거나 서버 모드를 쓴다. Chroma 내장 모드는 **잠금이 없어 오류 없이 열리지만** 여러 프로세스가 같은 폴더에 쓰면 손상될 수 있으므로, 동시에 쓰지 않도록 직접 주의한다.
- **다시 색인해야 할 때**: 청킹·파서를 바꿨으면 `make index ARGS=--force`. 임베딩 모델·벡터 차원·sparse 토크나이저를 바꿨으면 `make index ARGS=--recreate`(컬렉션을 새로 만든다). 다른 모델로 기존 컬렉션을 열면 `StoreMismatchError`로 멈춘다.
- **Chroma로 바꾸기**: `.env`에 `VECTOR_STORE=chroma`. 데이터는 `CHROMA_DIR`에 저장되고 텔레메트리는 꺼져 있다. 하이브리드 검색은 같은 결과를 파이썬에서 계산한다.
- **Chroma 자원 종료**: `build_store()`가 만든 저장소는 자기 클라이언트를 소유하므로 작업이 끝나면 `store.close()`로 닫는다. 임시 폴더 삭제 전에 닫아야 Windows 파일 잠금을 해제할 수 있다. `ChromaVectorStore`에 외부 클라이언트를 직접 주입한 경우 기본은 빌린 객체(`owns_client=False`)이며, 종료는 클라이언트를 만든 쪽에서 담당한다. 이 기본값은 같은 클라이언트를 공유하는 기존 코드의 동작을 유지한다.
- **서버 모드 계약 테스트**: `make qdrant-up` 후 `QDRANT_URL=http://localhost:6333 uv run --no-sync pytest tests/rag`. 로컬 모드는 엔진이 달라 주기적으로 서버 모드로도 돌린다.
- **실제 모델 스모크 테스트**(모델 다운로드 필요): `RAG_SLOW_TESTS=1 EMBEDDING_MODEL=BAAI/bge-m3 uv run --no-sync pytest tests/rag/test_real_model_smoke.py`. 모델을 이미 받았으면 `HF_HUB_OFFLINE=1`을 붙인다(붙이지 않으면 Hub 확인으로 수 분 멈출 수 있다)

## 문제가 생기면

| 증상 | 확인 |
|---|---|
| `uv sync --locked` 가 lock 불일치로 실패 | 누군가 `pyproject.toml`만 커밋한 경우. 그 PR에 `uv.lock` 반영을 요청한다. `--locked`를 빼서 우회하지 않는다 |
| `uv_build` 버전 경고 | 설치된 uv가 더 새 버전일 때 나오는 경고. 동작에는 영향 없음 |
| 5432 포트 사용 중 | 로컬에 이미 PostgreSQL이 떠 있음. 끄거나 compose 포트를 바꾼다 |
