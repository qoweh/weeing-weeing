---
name: ww-review-before-pr
description: weeing-weeing에서 PR을 올리거나 PR 브랜치에 push하기 전에, 깨끗한 환경 동작 확인과 프로젝트 규칙 점검으로 리뷰에서 지적받을 항목을 먼저 없앤다. "PR 전 점검", "셀프 리뷰", "ww-review-before-pr" 요청이나 `ww-pr` 직전에 사용.
---

# ww-review-before-pr — PR 전 셀프 리뷰

리뷰(팀원·Codex 자동 리뷰)를 여러 번 주고받는 대신, push 전에 지적받을 만한 것을 먼저 고친다. 두 관문을 **모두** 통과해야 `ww-pr`로 넘어간다.

## 범위 정하기

```bash
git fetch origin
git diff --name-only origin/main...HEAD     # 이 브랜치가 바꾼 파일
git status --short                          # 아직 커밋 안 한 변경
```

관문 1은 커밋된 내용으로 검사하므로, 커밋 안 한 변경이 있으면 먼저 커밋할지 사용자에게 묻는다.

## 관문 1 — 깨끗한 환경에서 동작

내 `.venv`·`.env`·캐시에 기대어 통과한 것이 아닌지, 처음 받은 팀원 환경으로 확인한다.

```bash
CLEAN=$(mktemp -d)`ww-clean`
git worktree add --detach "$CLEAN" HEAD
cd "$CLEAN"
UV_PROJECT_ENVIRONMENT="$CLEAN/.venv" uv sync --locked --no-install-project
UV_PROJECT_ENVIRONMENT="$CLEAN/.venv" make check
```

- `api/`를 바꿨으면 같은 환경에서 `make api`를 띄워 `/health`(와 바꾼 엔드포인트)를 호출해 본다.
- 문서(`README.md`, `docs/LOCAL_SETUP.md`)의 명령을 바꿨으면 그 명령을 그대로 실행해 본다.
- 끝나면 정리한다: `cd - && git worktree remove --force "$CLEAN"`.

## 관문 2 — 프로젝트 규칙 점검

먼저 기계적으로 잡히는 것부터 돌린다.

```bash
# A. 다른 모듈의 내부 파일 import (결과 중 interface·contracts가 아닌 것을 본다)
git grep -nE "from weeing_weeing\.[a-z_]+\.[a-z_]+ import" -- src
# B. plc가 api·agent·rag를 import하는지 (0건이어야 함)
git grep -nE "weeing_weeing\.(api|agent|rag)" -- src/weeing_weeing/plc
# C. 의존성 lock 정합
uv lock --check
# D. 시크릿
uv run --no-sync pre-commit run gitleaks --all-files
# E. 스킬 사본 동기화 (.agents/skills를 고쳤을 때)
uv run --no-sync python scripts/sync_skills.py --check
```

그다음 바뀐 파일을 아래 표로 하나씩 대조한다. 해당 없는 줄은 건너뛴다.

| 점검 | 확인 방법 | 올바른 형태 |
|---|---|---|
| 모듈 경계 | 명령 A 결과에서 다른 모듈의 `interface`가 아닌 내부 파일 import | 다른 모듈은 `interface.py`와 `contracts`만 import (docs/ARCHITECTURE.md) |
| plc 독립성 | 명령 B | 0건 |
| 계약 변경 | `contracts/`가 바뀌었는데 `docs/CONTRACTS.md`·`tests/contracts/`가 안 바뀜 | 같은 PR에서 함께 수정, PR 본문에 영향 모듈 |
| 의존성 | `pyproject.toml`만 바뀌고 `uv.lock`이 안 바뀜, 명령 C 실패 | 둘 다 커밋, `uv add`로만 추가 |
| 환경변수 | 코드에 새 `os.environ`/설정 키가 있는데 `.env.example`·`config.py`에 없음 | 셋을 함께, `.env.example`에는 비밀 값 없이 |
| 외부 호출 | Ollama·HTTP 호출에 timeout이 없음, 실패 시 예외가 그대로 터짐 | timeout 지정, 실패하면 `status=FAILED` 같은 정해진 결과로 |
| 근거 검증 | agent가 근거 없이 OK를 내거나 검증 오류를 삼킴 | `AnalysisResult` 검증 오류는 잡아서 `INSUFFICIENT_EVIDENCE`/`FAILED`로 |
| AI 작성 금지 칸 | agent 코드가 보고서 `maintenance`·`approval`을 채움 | AI는 `ai_analysis`까지만 |
| 시크릿 | 명령 D | 통과. `.env`·키·개인정보 없음 |
| 스킬 | `.claude/skills`를 직접 고침, 명령 E 실패 | 원본 `.agents/skills`만 고치고 `scripts/sync_skills.py`로 복사 |
| 컨테이너 포트 | compose `ports`가 `127.0.0.1:`로 시작하지 않음 | 로컬 개발은 `127.0.0.1:<포트>:<포트>` |
| 테스트 | 새 로직에 테스트가 없음, 테스트가 실제 Ollama·네트워크를 부름 | CI에서 돌 수 있게 가짜 객체(`interface`의 Protocol 구현)로 대체 |
| 문서와 코드 | 문서·주석의 명령·키 이름·경로가 실제와 다름 | 바꾼 쪽에 맞춰 함께 수정 |
| 큰 파일 | `git diff --stat origin/main...HEAD`에 수 MB 이상 파일 | `data/README.md`에 출처 기록, 수십 MB 이상은 커밋하지 않음 |

### 같은 종류 결함은 전부 찾는다

하나를 발견하면 같은 패턴을 레포 전체에서 `git grep`으로 찾아 함께 고친다. 리뷰에서 "여기도 같은 문제"라는 지적이 반복되는 가장 흔한 원인이다.

자주 나온 지적 예시:
- **규칙과 실제 명령이 다름**: CLAUDE.md는 `uv sync --no-install-project`인데 Makefile·CI·문서는 다른 명령을 씀
- **검증의 빈틈**: 목록이 비어 있으면 반복문이 돌지 않아 검사를 그냥 통과함(빈 `evidence_ids`)

### 필요하면 다른 눈으로 한 번 더

변경이 크면(파일 10개 이상 또는 `contracts/` 변경) 서브에이전트에게 diff를 넘겨 위 표 기준으로 독립 리뷰를 받는다. 오탐이라고 판단한 항목은 PR 본문 맨 아래 "리뷰 노트"에 이유와 함께 적는다.

## 보고

| 관문 | 결과 | 내용 |
|---|---|---|
| 1 깨끗한 환경 | ✅/❌ | 실행한 명령과 테스트 수 |
| 2 규칙 점검 | ✅/❌ | 고친 항목, 남긴 항목(이유) |

둘 다 ✅일 때만 `ww-pr`로 넘어간다. ❌가 있으면 고칠지 사용자에게 묻는다.
