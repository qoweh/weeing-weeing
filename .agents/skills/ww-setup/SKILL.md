---
name: ww-setup
description: weeing-weeing 레포를 처음 받은 팀원(또는 새 머신)의 로컬 개발 환경을 단계별로 설치하고 실제 동작까지 확인한다. "환경 세팅", "처음 설치", "로컬 환경 맞춰줘", "ww-setup" 요청에 사용.
---

# ww-setup — 로컬 개발 환경 설치·검증

`docs/LOCAL_SETUP.md`의 순서를 그대로 실행하면서 단계마다 **실제로 동작하는지 확인**한다. 문서와 실제가 다르면 문서를 고치자고 제안한다(고치는 건 사용자 승인 후).

## 지켜야 할 것

- 소스 코드(`src/`, `tests/`)는 고치지 않는다. 이 스킬은 환경만 만든다.
- 이미 있는 `.env`는 덮어쓰지 않는다. `.env`의 값은 화면·로그에 출력하지 않는다.
- 큰 다운로드(임베딩·리랭커 모델, Docker 이미지)는 이름과 대략 크기를 말하고 사용자 동의를 받은 뒤 받는다.
- 볼륨 삭제(`docker compose down -v`)처럼 데이터를 지우는 명령은 쓰지 않는다.
- 모든 단계는 다시 실행해도 안전해야 한다.

## 단계

### 0. 위치 확인
레포 루트인지 확인한다: `pyproject.toml`의 `name = "weeing-weeing"`. 아니면 중단하고 경로를 묻는다.

### 1. 도구 점검
```bash
echo "uv=$(uv --version 2>&1) | git=$(git --version 2>&1) | docker=$(docker compose version 2>&1 | head -1)"
```
- uv가 없으면 설치 명령을 안내한다(`docs/LOCAL_SETUP.md` 0절). 설치는 사용자가 직접 한다.
- docker는 담당 파트에 따라 나중에 필요하므로 없어도 계속 진행하고 결과 표에 표시한다.

### 2. 의존성 설치
```bash
uv sync --locked --no-install-project
```
lock 불일치로 실패하면 `--locked`를 빼지 말고, 누가 `pyproject.toml`만 바꿨는지 `git log -p -- pyproject.toml uv.lock`으로 찾아 보고한다.

### 3. `.env`
`.env`가 없을 때만 `cp .env.example .env`. 있으면 `.env.example`에만 있는 키 이름(값 말고)을 비교해 빠진 키를 알려 준다.

### 4. 검사
```bash
make check        # make가 없으면 docs/LOCAL_SETUP.md 1절의 uv run --no-sync 명령
uv run --no-sync pre-commit install
```

### 5. API
`make api`를 백그라운드로 띄우고 `curl -sf localhost:8000/health`가 `"status":"ok"`를 돌려주는지 확인한 뒤 프로세스를 끈다.

### 6. PostgreSQL (2차부터, docker가 있을 때)
```bash
docker compose up -d postgres
docker compose ps postgres          # healthy 확인
docker compose exec postgres pg_isready -U weeing -d weeing
```
5432 포트 충돌이면 `docs/LOCAL_SETUP.md` 문제 해결 표를 따른다.

### 7. Claude API 키 (Agent·챗봇 담당 또는 사용자가 원할 때)
- 로컬 LLM(Ollama)은 쓰지 않는다. 받을 LLM 모델이 없다.
- `.env`에 `ANTHROPIC_API_KEY` 값이 들어 있는지만 확인한다(값은 출력하지 않는다). 빈 값 줄(`ANTHROPIC_API_KEY=`)은 `ant auth login` 프로필을 가리므로 주석 처리를 안내한다. 키는 사용자가 직접 넣는다.
- 키가 있으면 사용자 동의를 받아 `make llm-check`(API 비용 발생)로 확인한다.
- 사용량 기록(`docs/USAGE_TRACKING.md`): `LLM_USER`(본인 GitHub 핸들)와 `LANGFUSE_BASE_URL`·`LANGFUSE_PUBLIC_KEY`·`LANGFUSE_SECRET_KEY`가 들어 있는지만 확인한다(값 출력 금지). 키는 김민우에게 개별로 받는다. 없어도 개발은 되므로 막지 않고 보고에 적는다.

## 보고

마지막에 표 하나로 보고한다.

| 단계 | 결과 | 비고 |
|---|---|---|
| 도구 | ✅/⚠️/❌ | 없는 도구 |
| 의존성 | | |
| .env | | 빠진 키 이름 |
| make check | | 테스트 수 |
| pre-commit | | |
| API /health | | |
| PostgreSQL | | 건너뛰었으면 이유 |
| Claude API 키 | | 있음/없음(값 출력 금지) |
| 사용량 기록 | | LLM_USER·LANGFUSE_* 있음/없음(값 출력 금지) |

실패한 단계는 숨기지 않고 오류 메시지와 다음 할 일을 적는다.
