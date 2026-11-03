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
make env-check                          # .env.example과 비교: 빠진·낡은·중복·주석 변수 (값은 출력 안 함)
uv run --no-sync pytest                 # 테스트
uv run --no-sync ruff check . && uv run --no-sync ruff format --check .
uv run --no-sync pre-commit install     # 커밋 전 자동 검사 (1회)
```

`make`가 있으면 위 명령을 `make setup`, `make check`로 줄여 쓸 수 있다(`make help`).
Makefile은 하위 프로세스에 `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`을 자동 전달한다.
Windows PowerShell에서도 별도 환경변수 설정 없이 `make check`를 실행하면 Python의
기본 텍스트 인코딩과 표준 입출력에 UTF-8이 적용된다. Linux에서도 같은 설정을 사용한다.
이 설정은 해당 make 실행과 하위 프로세스에만 적용하며 터미널의 전역 설정은 바꾸지 않는다.
`make` 없이 `uv run`을 직접 실행할 때는 필요하면 두 환경변수를 직접 설정한다.

Windows와 Linux 모두 GNU make와 uv가 있으면 같은 Makefile을 사용한다.
`make help`는 Python으로 명령 목록을 출력하므로 `grep`·`awk`가 필요 없다.
`PYTHONPATH`도 Makefile에서 저장소의 `src` 경로로 자동 설정하므로 PowerShell에서
`PYTHONPATH=src`를 명령 앞에 붙일 필요가 없다. 추가 옵션은 예를 들어
`make rag-e2e ARGS="--backends qdrant,chroma"`처럼 전달한다.
`ARGS`는 환경변수로 Python 실행기에 전달한 뒤 인수 배열로 실행한다. 공백은 큰따옴표로 묶는다.
Windows용 make는 시스템 언어에 따라 한글·이모지 인자를 Python 실행 전에 손상시킬 수 있다.
Python의 UTF-8 설정이나 `chcp`만으로는 make의 인자 변환을 고칠 수 없다.
이 경우 인자를 UTF-8 파일에 적고 ASCII 이름의 파일 경로를 `ARGS_FILE`로 전달한다.
파일은 인용부호를 포함한 한 줄의 인수 문자열이며, UTF-8 BOM과 마지막 줄바꿈을 허용한다.
`ARGS`와 `ARGS_FILE`은 함께 지정하지 않는다. 실제 키·토큰을 인수 파일에 적지 않는다.

```powershell
'"모터 과열 점검 절차" --asset-id BLDC-001' | Set-Content -Encoding utf8 "$env:TEMP\ww-chat-args.txt"
make chat ARGS_FILE="$env:TEMP\ww-chat-args.txt"
```

위 `chat` 명령은 실제 Claude API 비용이 발생한다. 터미널의 기존 `ARGS` 설정이 있다면 먼저 비운다.
임시 폴더 경로에도 시스템 언어로 표현할 수 없는 문자가 있으면 ASCII 경로의 인수 파일을 사용한다.
CI의 `Make compatibility`는 Windows·Linux에서 실제 make의 환경변수·한글/공백 인수
전달을 검사한다. DB·Docker·모델·Claude 인증은 각 명령의 기존 실행 요건을 따른다.

파일 인코딩은 UTF-8을 기본으로 사용한다. Python 코드에서 텍스트 파일을 읽고 쓸 때는
`encoding="utf-8"`을 명시해 Windows의 기본 인코딩(CP949)에 영향을 받지 않게 한다.
FAQ 카탈로그 로더는 UTF-8(BOM 포함)을 먼저 시도하고, 디코딩이 실패한 경우 CP949로
읽는다. 두 인코딩으로 모두 읽을 수 없거나 TOML·내용 검증에 실패하면 기존처럼
`FaqCatalogError`를 반환한다. 기존 파일을 자동 변환하거나 덮어쓰지는 않는다.

Windows에서 심볼릭 링크 생성 권한이 없으면 실제 링크를 만드는 문서 검색 테스트
1개만 `WinError 1314` 사유로 건너뛴다. 다른 파일 오류는 테스트 실패로 보고한다.
상대 경로(`../`)와 절대 경로로 업로드 폴더 밖의 본문을 읽을 수 없는지는 권한과
무관하게 별도 테스트로 검사한다.

> 프로젝트 자체는 설치하지 않는 것이 팀 규칙이다(`--no-install-project`). 옵션 없이 `uv run`을 쓰면 실행 전에 프로젝트를 설치하므로 `uv run --no-sync`로 실행한다. 대신 의존성이 바뀌면 `make setup`(또는 위 `uv sync` 명령)을 다시 실행한다. 패키지 import는 `pytest`의 `pythonpath`와 `uvicorn --app-dir src`가 맡는다.

> ⚠️ `pip install` 대신 반드시 `uv add <패키지>`(개발용은 `uv add --dev`)를 쓴다. `pyproject.toml`과 `uv.lock`을 함께 커밋해야 팀원 환경이 같아진다. 다른 사람 변경을 pull 받은 뒤에는 `make setup`을 한 번 실행한다.

## 2. API 띄우기

```bash
uv run --no-sync --env-file .env uvicorn --app-dir src weeing_weeing.api.app:app --reload   # 또는 make api
```

http://localhost:8000/health 와 http://localhost:8000/docs 에서 확인한다.

## 3. DB (PostgreSQL)

문서 목록(`document` 테이블)이 DB에 있어서 웹 문서 관리 API에 DB가 필요하다. 테이블과 사용법은 [DB.md](DB.md). 로그인할 시연 계정은 `make seed-users`([AUTH.md](AUTH.md)).

```bash
docker compose up -d postgres     # 또는 make db-up
docker compose ps                 # postgres 가 healthy 인지 확인
```

접속 정보는 `.env`의 `DATABASE_URL`. 데이터는 docker 볼륨 `postgres_data`에 남는다. 스키마는 API가 시작할 때 최신으로 올린다(직접 올리려면 `make db-migrate`).

**Docker 없이 개발할 때**: `.env`에 `DATABASE_URL=sqlite:///storage/dev.db`. 같은 코드가 파일 하나(`storage/dev.db`, git 밖)로 동작한다. 지우면 등록 기록도 사라지므로 필요한 문서를 웹에서 다시 등록한다. 통합 시험·시연은 PostgreSQL로 한다.

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
- 사용량 기록: `.env`에 `LLM_USER`(본인 GitHub 핸들)와 `LANGFUSE_*`(개별로 받은 키)를 넣으면 호출마다 토큰·비용이 홈서버 Langfuse에 남는다. 비어 있으면 기록하지 않고, 서버가 꺼져 있어도 호출은 그대로 된다([USAGE_TRACKING](USAGE_TRACKING.md))

## 5. RAG 색인 (벡터 DB)

문서 목록은 DB `document` 테이블이 원본이다(3절). 받을 모델은 없다. 기본 설정(`EMBEDDING_PROVIDER=hashing`, `RERANKER_MODEL=` 빈 값)은 외부 호출 없이 서버 안에서 임베딩한다([EMBEDDING_API](EMBEDDING_API.md)). 관제 담당자로 로그인해 HMI의 **문서 등록**에서 PDF를 올린다. 파싱·청킹·임베딩·벡터 저장은 자동으로 진행한다. 원본 PDF는 `storage/uploads/`, 문서 정보와 상태는 DB에 저장한다. 운영 카탈로그나 별도 일괄 색인 명령은 사용하지 않는다. Voyage 임베딩·리랭크 API를 쓰려면 `.env`에 `EMBEDDING_PROVIDER=voyage`·`VOYAGE_API_KEY`·`RERANKER_MODEL=rerank-3-lite`를 넣는다(문서 본문이 외부로 나간다, [AI_DATA_SECURITY](AI_DATA_SECURITY.md)).

기존 문서와 같은 ID를 입력하면 문서 종류와 설비 ID가 동일한 경우에만 교체할 수 있다.
등록 화면에서 기존 파일과 새 파일을 확인하고 교체를 승인해야 한다. 버전이 같거나 낮으면
경고하며, PDF 파일명에서 버전을 찾지 못하면 기본 `1.0`을 사용한다. 교체가 완료되면
기존 검색 자료도 새 문서의 청크로 교체된다. 같은 ID의 문서 종류나 설비가 다르면 다른
문서 ID를 입력해야 한다.

| | Qdrant 로컬 모드 (기본) | Qdrant 서버 모드 |
|---|---|---|
| 설정 | `QDRANT_URL` 비움, `QDRANT_PATH=storage/qdrant` | `QDRANT_URL=http://localhost:6333` |
| 준비 | 없음 | `make qdrant-up` (= `docker compose --profile qdrant up -d qdrant`) |
| 정체 | qdrant-client 안의 파이썬 재구현, 폴더에 저장 | 실제 Qdrant 엔진. 대시보드 http://localhost:6333/dashboard |
| 동시 접근 | **한 폴더를 한 프로세스만** 연다 | 여러 프로세스 가능 |
| 용도 | 개발·단위 테스트 | 통합 시험·시연·운영 |

- **한 프로세스만 쓰기**: Qdrant 로컬 모드는 같은 폴더를 한 프로세스만 열 수 있다. API가 로컬 폴더를 사용 중이면 별도 점검 프로그램에서 같은 폴더를 열지 않는다. 동시 접속·대시보드 확인이 필요하면 `QDRANT_URL` 서버 모드를 쓴다. Chroma 내장 모드도 같은 폴더에 여러 프로세스가 동시에 쓰지 않는다.
- **임베딩 공급자·모델·청킹 변경**: 운영 일괄 재구축 명령은 제공하지 않는다. 공급자·모델·차원·sparse 토크나이저를 바꾸면 기존 컬렉션과 호환되지 않으므로 새 컬렉션을 준비하고 필요한 문서를 웹에서 재등록한다. 모델 변경 전 기존 DB·원본·컬렉션을 보관한다.
- **Chroma로 바꾸기**: `.env`에 `VECTOR_STORE=chroma`. 데이터는 `CHROMA_DIR`에 저장되고 텔레메트리는 꺼져 있다. 하이브리드 검색은 같은 결과를 파이썬에서 계산한다.
- **Chroma 자원 종료**: `build_store()`가 만든 저장소는 자기 클라이언트를 소유하므로 작업이 끝나면 `store.close()`로 닫는다. 임시 폴더 삭제 전에 닫아야 Windows 파일 잠금을 해제할 수 있다. `ChromaVectorStore`에 외부 클라이언트를 직접 주입한 경우 기본은 빌린 객체(`owns_client=False`)이며, 종료는 클라이언트를 만든 쪽에서 담당한다. 이 기본값은 같은 클라이언트를 공유하는 기존 코드의 동작을 유지한다.
- **서버 모드 계약 테스트**: `make qdrant-up` 후 `QDRANT_URL=http://localhost:6333 uv run --no-sync pytest tests/rag`. 로컬 모드는 엔진이 달라 주기적으로 서버 모드로도 돌린다.
- **실제 임베딩 API 스모크 테스트**(유료, 본인 터미널에서): `RAG_LIVE_API_TESTS=1 uv run --no-sync pytest tests/rag/test_live_embedding_api.py`. `VOYAGE_API_KEY`가 필요하고 수백 토큰을 쓴다

## 문제가 생기면

| 증상 | 확인 |
|---|---|
| `uv sync --locked` 가 lock 불일치로 실패 | 누군가 `pyproject.toml`만 커밋한 경우. 그 PR에 `uv.lock` 반영을 요청한다. `--locked`를 빼서 우회하지 않는다 |
| `uv_build` 버전 경고 | 설치된 uv가 더 새 버전일 때 나오는 경고. 동작에는 영향 없음 |
| 5432 포트 사용 중 | 로컬에 이미 PostgreSQL이 떠 있음. 끄거나 compose 포트를 바꾼다 |
