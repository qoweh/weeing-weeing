# 운영 명령 모음 (ops)

자주 쓰는 명령을 스크립트로 묶었다. 명령 목록은 언제든 `help`로 본다.

| 어디서 | macOS·Linux·Git Bash | Windows PowerShell | 하는 일 |
|---|---|---|---|
| 내 PC(로컬 개발) | [`ops/local.sh`](local.sh) | [`ops\local.ps1`](local.ps1) | 설치·검사·로컬 DB/Qdrant·백엔드·프론트·HMI 실행 |
| 내 PC → 운영 서버 | [`ops/aws.sh`](aws.sh) | [`ops\aws.ps1`](aws.ps1) | 접속·터널, 그리고 아래 서버 명령을 SSH로 실행 |
| 운영 서버 안 | [`ops/server.sh`](server.sh) | (같음) | 상태·로그·볼륨·RAG·DB 확인·재시작 |
| 운영 서버 안 | [`ops/server-deploy.sh`](server-deploy.sh) | (같음) | Actions 없이 서버에서 직접 빌드·배포·롤백([DEPLOY](../docs/DEPLOY.md#서버에서-직접-빌드배포-actions-없이)) |

```bash
ops/local.sh help         # macOS·Linux
ops/aws.sh help
```

```powershell
.\ops\local.ps1 help      # Windows
.\ops\aws.ps1 help
```

- 서버 명령은 `server.sh` 한 파일에만 있다. `aws.sh`·`aws.ps1`은 이 파일을 SSH로 보내 서버 임시 파일로 실행하고 지운다. 서버에 따로 설치할 것이 없다
- `.env` 값은 출력하지 않는다. `rag`만 비밀이 아닌 RAG 설정 값과 키 유무(설정됨/없음)를 보여 준다
- 서버 명령의 인자(서비스 이름·줄 수)는 영문·숫자·`-`·`_`만 받는다
- Windows에서 "스크립트를 실행할 수 없습니다"가 나오면 한 번만: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- `local.ps1`은 make 없이 Makefile과 같은 명령을 직접 부른다. Makefile 대상을 바꾸면 `local.ps1`도 같이 고친다

## 로컬

처음 한 번:

| 순서 | macOS·Linux | Windows |
|---|---|---|
| 1. 의존성 | `ops/local.sh setup` | `.\ops\local.ps1 setup` |
| 2. 설정 | `cp .env.example .env` 후 값 채우기 | `Copy-Item .env.example .env` 후 값 채우기 |
| 3. DB | `ops/local.sh db` | `.\ops\local.ps1 db` |
| 4. 계정 | `ops/local.sh seed` | `.\ops\local.ps1 seed` |
| 5. 팀 문서 | `ops/local.sh seed-docs` | `.\ops\local.ps1 seed-docs` |

평소에는 터미널(PowerShell 창) 3개를 켠다:

| 대상 | 명령 (`local.sh` / `local.ps1` 같음) | 주소 |
|---|---|---|
| 백엔드 | `api` | http://localhost:8000/docs |
| 프론트(Next.js) | `front` | http://localhost:3100 (`/api` → 8000) |
| HMI(Vite) | `hmi` | http://localhost:5173 (`/api` → 8000) |

| 명령 | 원래 명령 |
|---|---|
| `setup` | `uv sync --locked --no-install-project`, `frontend`·`hmi/web`에서 `npm ci` |
| `check` | `make check` (= `ruff check .`, `ruff format --check .`, `pytest`, `sync_skills.py --check`) |
| `env-check` | `make env-check` |
| `db` | `docker compose up -d postgres`, `alembic upgrade head` |
| `qdrant` | `docker compose --profile qdrant up -d qdrant` (`.env`에 `QDRANT_URL=http://localhost:6333`일 때만) |
| `ps` / `logs [서비스]` | `docker compose --profile qdrant ps` / `logs -f --tail 100 <서비스>` |
| `volumes` | `docker volume ls`, `docker system df -v` |
| `down` | `docker compose --profile qdrant down` (볼륨은 남는다) |
| `api` | `uv run --no-sync --env-file .env uvicorn --app-dir src weeing_weeing.api.app:app --reload` |
| `front` / `hmi` | `cd frontend && npm run dev` / `cd hmi/web && npm run dev` |
| `seed` | `make seed-users` |
| `seed-docs [--replace]` | `make seed-docs` (팀 문서 미리 등록, 같은 파일은 건너뜀) |
| `reindex-reports` | `make index-reports ARGS=--all` |

- 로컬 볼륨 이름은 `<폴더 이름>_postgres_data`처럼 체크아웃 폴더 이름을 앞에 붙인다. worktree마다 따로 생긴다
- Docker Desktop(macOS·Windows)의 볼륨 경로는 Docker VM 안이라 Finder·탐색기에서 보이지 않는다

## 운영 서버

먼저 SSH 키를 등록하고 `~/.ssh/config`(Windows: `C:\Users\<이름>\.ssh\config`)에 별칭 `ww-team`을 만든다([AWS_ACCESS](../docs/AWS_ACCESS.md) 2절). 별칭이 다르면 `WW_HOST=<별칭> ops/aws.sh ...` / `$env:WW_HOST = '<별칭>'`.

```bash
ops/aws.sh ps             # 컨테이너 상태 (api는 healthy)
ops/aws.sh logs api       # api 로그 따라가기 (Ctrl+C)
ops/aws.sh tunnel         # DB localhost:15432, Qdrant http://localhost:16333/dashboard
ops/aws.sh rag            # RAG 설정, Qdrant 컬렉션·포인트 수, DB 문서·보고서 색인 상태
```

Windows는 `ops/aws.sh`를 `.\ops\aws.ps1`로 바꾸면 된다.

| 명령 | 서버에서 실행되는 원래 명령 (`cd ~/weeing-weeing` 뒤) |
|---|---|
| `ssh` | `ssh ww-team` |
| `tunnel` | `ssh -N -L 15432:localhost:5432 -L 16333:localhost:6333 ww-team` (내 PC에서) |
| `ps` / `images` | `docker compose ps` / `docker compose images` |
| `health` | `curl -fsS localhost/api/health` |
| `logs [서비스] [줄수]` | `docker compose logs -f --tail 100 api` (서비스: api·frontend·web·postgres·qdrant) |
| `logs-all [줄수]` | `docker compose logs -f --tail 50` |
| `volumes` | `docker volume ls --filter label=com.docker.compose.project=weeing-weeing`, `docker volume inspect`, `docker system df -v` |
| `disk` | `df -h /`, `docker system df` |
| `rag` | `.env`의 RAG 줄만 grep(끝 공백 표시), `curl localhost:6333/collections`, `document`·`report_index_job` 상태별 개수 |
| `db` | `docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'` |
| `env-keys` | `.env`의 변수 이름만 |
| `env-check` / `env-sync` | 떠 있는 api 이미지로 `docker run --network none ... python check_env.py --no-shell-check` / `--add-missing` (서버 `.env.example`·`check_env.py`는 배포 워크플로가 복사) |
| `seed-docs [--replace]` | `docker compose exec -T api python scripts/seed_documents.py` |
| `reindex-reports` / `retry-reports` | `docker compose exec -T api python scripts/index_reports.py --all` / `--retry-failed` |
| `restart <서비스>` | `docker compose restart <서비스>` |
| `up` | `docker compose up -d` (`.env`를 바꾼 뒤) |
| `pull-up` | `docker compose pull && docker compose up -d` |
| `langfuse-ps` / `langfuse-logs` | `cd ~/langfuse && docker compose ps` / `logs -f langfuse-web` |
| `deploys` | `gh run list --workflow deploy.yml` (내 PC에서) |

서버 안 위치:

| 위치 | 내용 |
|---|---|
| `~/weeing-weeing/docker-compose.yml` | 앱 구성. 배포 워크플로가 `deploy/docker-compose.prod.yml`로 덮어쓴다 |
| `~/weeing-weeing/.env` | 앱 비밀 값. **통째로 `.env.example`로 덮어쓰지 않는다**(빠진 줄만 추가) |
| `~/langfuse/` | Langfuse 구성(`deploy/langfuse/`)과 비밀 값. 앱 배포와 따로 움직인다([DEPLOY](../docs/DEPLOY.md#ec2-자체-langfuse-deploylangfuse)) |
| Docker 볼륨 `weeing-weeing_*` | `postgres_data`(DB), `qdrant_data`(벡터), `storage`(업로드 원본), `outputs`(사건 기록), `caddy_data`·`caddy_config`(인증서). 실제 경로는 `volumes` |

- 배포는 `main`에 병합되면 GitHub Actions가 한다([DEPLOY](../docs/DEPLOY.md)). `pull-up`은 워크플로가 실패했을 때만 쓴다
- `.env`를 바꿨으면 `up`으로 다시 띄워야 반영된다(`restart`는 `.env`를 다시 읽지 않는다)
- `rag`에서 Qdrant 컬렉션이 비어 있는데 DB `document`가 `indexed`로 남아 있으면 검색 근거가 없는 상태다. `seed-docs`와 `reindex-reports`를 실행한다([COMMERCIAL_MODELS](../docs/COMMERCIAL_MODELS.md) 2-5)
- 운영 DB는 조회 위주로 쓰고, 수정·삭제는 팀에 알린 뒤 한다
- 서버 안에서 직접 쓰려면 `scp ops/server.sh ww-team:~/` 후 `bash ~/server.sh ps`
- 서버는 2026-11-14 00:00에 자동으로 꺼진다
