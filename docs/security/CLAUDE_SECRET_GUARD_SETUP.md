# Claude Code에서 환경 파일 읽기 차단 확인

작성일: 2026-11-06. 실제 `.env`·`.env.example`·전역 설정(`~/.claude`)은 열지 않는다.
Codex용 설정과 확인 순서는 [SECRET_GUARD_SETUP.md](SECRET_GUARD_SETUP.md)를 본다.

## 이번에 준비한 설정

[`.claude/settings.json`](../../.claude/settings.json)은 팀이 함께 쓰는 프로젝트 설정이다.
실제 키가 없고, 저장소 기준 상대 경로만 써서 macOS·Windows 어디서 받아도 같은 뜻이다.
모델·hook·plugin·statusline 같은 개인 설정은 넣지 않았다. 개인 설정은
`.claude/settings.local.json`(git 제외)이나 `~/.claude/settings.json`에 둔다.

- Claude의 파일 도구(Read·Edit·Write·Grep·Glob)로 `.env`·`.env.*`를 읽거나 고치지 못한다.
  루트와 하위 폴더 모두 해당하며, Codex 설정과 같이 `.env.example`도 포함한다.
- Claude가 Bash로 `cat`·`head`·`tail`·`sed` 같은 파일 명령을 쓰거나 `< .env`처럼
  리다이렉트할 때도 같은 규칙이 적용된다.
- `cat *.env*`, `source *.env*`, `printenv`, `env`(인자 없이 전체 출력),
  `uv run --env-file …`을 명시적으로 거부한다. Windows PowerShell 도구에서는
  `Get-Content *.env*`와 `Get-ChildItem Env:*`(`dir env:`·`ls env:` 포함)를 거부한다.
- sandbox를 켜면 Bash가 실행한 모든 프로세스(Python 스크립트 포함)에서 `.env`·`.env.*`
  읽기를 OS 수준에서 막고, 프로젝트 키 환경변수
  (`ANTHROPIC_API_KEY`·`VOYAGE_API_KEY`·`LANGFUSE_*_KEY`·`POSTGRES_PASSWORD`·
  `WW_TELEMETRY_TOKEN`·`AWS_ACCESS_KEY_ID`·`AWS_SECRET_ACCESS_KEY`·`AWS_SESSION_TOKEN`)를 지운다.
  **sandbox는 공유 설정에서 켜지 않았다.** 이유는 아래 "sandbox를 기본으로 켜지 않은 이유"에 있다.

## Codex 설정과 비교

| Codex(`.codex/config.toml`) | Claude Code(`.claude/settings.json`) |
|---|---|
| `.env`·`.env.*`·`**/.env`·`**/.env.*` 읽기 거부 | `permissions.deny`의 `Read`·`Edit` 규칙으로 같은 범위를 거부. 항상 적용 |
| 셸 명령 파일 읽기 거부(샌드박스) | `sandbox.filesystem.denyRead`에 같은 경로. sandbox를 켠 사람에게만 적용 |
| 셸 네트워크 끔 | 끄지 않음. 아래 이유 참고 |
| `*_KEY`·`*_TOKEN`·`*_SECRET`·`*_PASSWORD`·`AWS_*` 제외 | 와일드카드를 지원하지 않아 이름을 하나씩 적음(`sandbox.credentials.envVars`). sandbox를 켠 사람에게만 적용 |

## sandbox를 기본으로 켜지 않은 이유

`sandbox.enabled`를 공유 설정에서 `true`로 두면 팀원 전원의 평소 작업이 깨진다.

1. **테스트 실패**: `tests/test_config.py`가 `.env.example`을 읽는다. sandbox가
   `.env.*` 읽기를 막으면 Claude가 실행한 `make check`가 실패한다.
2. **`git push` 실패**: 이 저장소의 원격은 SSH(`git@github.com:`)다. 공식 문서에 따르면
   macOS sandbox 안에서는 SSH 원격으로 `git fetch`·`pull`·`push`가 실패한다.
3. **네트워크 확인 요청**: sandbox의 허용 도메인 목록은 빈 상태로 시작한다. `uv sync`·`gh`가
   새 호스트에 접속할 때마다 확인을 요청하고, auto 모드에서는 분류기가 거절할 수 있다.
   Codex처럼 네트워크를 완전히 끄는 설정은 이 문제가 더 크기 때문에 넣지 않았다.
4. **native Windows 미지원**: native Windows에서는 sandbox 없이 명령을 실행한다(WSL2는 지원).
   그래서 `failIfUnavailable`도 넣지 않았다. 넣으면 Windows 팀원은 Claude Code를 시작할 수 없다.

차단 경로와 환경변수 목록은 공유 설정에 미리 넣어 두었다. 원하는 사람은 다음 중 하나로
자기 컴퓨터에서만 켠다. 위 1~3번 영향을 감수해야 한다.

- Claude Code 세션에서 `/sandbox`를 실행해 모드를 고른다(`.claude/settings.local.json`에 저장된다).
- 또는 `.claude/settings.local.json`에 `{"sandbox": {"enabled": true}}`를 넣는다.

## macOS / Windows 참고

- **macOS**: sandbox는 내장 Seatbelt를 쓰므로 따로 설치할 것이 없다.
  `permissions.deny` 규칙은 sandbox 여부와 상관없이 적용된다.
- **Windows(native)**: 경로는 매칭 전에 POSIX 형태로 바뀌므로 `**/.env` 같은 상대 규칙을
  그대로 쓴다. sandbox가 없으므로 OS 수준의 읽기 차단과 환경변수 제거는 적용되지 않는다.
  이 환경에서 실제로 동작하는 것은 파일 도구 거부와 Bash·PowerShell 명령 거부 규칙뿐이다.
- **Windows(WSL2)**: `bubblewrap`·`socat`을 설치하면 sandbox를 쓸 수 있다. `/sandbox`
  화면에 빠진 항목이 표시된다.
- 공유 설정은 Claude Code를 **저장소 루트에서 시작해야** 읽힌다.
  `deny` 규칙은 폴더 신뢰(trust) 여부와 상관없이 바로 적용된다.

## 쉬운 확인 순서

1. 실제 키를 넣지 않은 상태를 유지한다. 실제 `.env`는 만들거나 열지 않는다.
2. 사용자가 자기 터미널에서 가짜 파일을 만든다. 예: `echo FAKE_ONLY=canary > .env.canary`
   (`.gitignore`가 `.env.*`를 제외하는지 `git status`로 확인한다).
3. 저장소 루트에서 Claude Code 새 세션을 열고 `/status`의 `Setting sources`에
   프로젝트 공유 설정 항목이 있는지 확인한다. `claude doctor`에 설정 오류가 없어야 한다.
4. 새 세션에 다음과 같이 요청한다.

   > 가짜 `.env.canary`만 읽기 차단을 재검사해줘. Read 도구와 Bash `cat` 각각에 대해
   > 내용은 출력하지 말고 읽기 성공·접근 거부만 알려줘. 실제 `.env`와 `.env.example`은 읽지 마.

5. 두 경로 모두 "denied by your permission settings" 같은 **접근 거부**가 나와야 하고,
   `README.md` 같은 정상 파일은 읽혀야 한다. 파일 없음·도구 오류는 차단 성공이 아니다.
6. sandbox를 켠 사람만 추가로 `uv run --no-sync python -c "open('.env.canary').read()"`가
   권한 오류로 실패하는지 확인한다. 이때도 내용은 출력하지 않는다.
7. 확인이 끝나면 사용자가 `.env.canary`를 직접 지운다.

## 한계와 절충

- **`permissions.deny`는 OS 격리가 아니다.** 파일 이름을 직접 적은 명령만 잡는다.
  `grep -r 패턴 .`처럼 이름을 적지 않는 명령이나, 파일을 직접 여는 Python·Node 스크립트는
  막지 못한다. 이를 막으려면 sandbox가 필요하다(위의 opt-in).
- Bash 규칙은 명령 문자열 기준이다. `/usr/bin/printenv`, `bash -c '…'`, `export -p`, `set` 같은
  변형은 일부 잡지 못한다. 키 조회 금지는 CLAUDE.md의 행동 규칙으로도 함께 지킨다.
- `env *`는 `env FOO=1 명령` 같은 정상 사용까지 막기 때문에 넣지 않았다. 인자 없는 `env`만 막는다.
- **`.env.example`도 Claude가 읽거나 고칠 수 없다.** 과거에 실제 키가 들어간 적이 있어서
  일부러 차단 범위에 넣은 절충이다. 새 환경변수를 `.env.example`에 추가해야 하면 Claude가
  변경할 키 이름과 설명을 알려 주고, **사용자가 직접 편집**한다.
- IDE 연결 시 열린 파일·선택 영역 문맥에도 Read deny를 "최대한" 적용한다고만 문서에 나와 있다.
  비밀 파일 탭은 닫아 두고, IDE 자동 문맥 설정을 따로 확인한다.
- 다른 팀원이 개인 설정에서 `allow` 규칙을 추가해도 `deny`가 우선한다. 다만 각자 컴퓨터의
  관리형·CLI 설정이나 `--setting-sources`로 프로젝트 설정을 빼면 적용되지 않는다.
- 환경변수 제거 목록은 이름을 하나씩 적은 것이다. 새 키 환경변수를 추가하면 이 목록에도 추가한다.
  sandbox와 별개로 셸에서 `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`을 설정하면 이름·값 모양으로
  자격 증명을 지운다. 단, 이 방식도 `GITHUB_TOKEN`·`GH_TOKEN`은 지우지 않는다.

## 실제 API 실행

이 설정은 Claude Code 에이전트에만 적용된다. 사용자가 자기 터미널에서 실행하는
`make chat`·`uv run --env-file .env …`에는 영향이 없다. 실제 인증 확인과 유료 LLM 실행은
사용자가 자기 터미널에서 직접 한다. 설정 파일을 만들었다고 보호 완료로 보지 않는다.
새 세션에서 위 확인 순서의 결과를 기록한 뒤 실제 키를 쓸지 판단한다.

근거:
[권한 규칙 문법(Read·Edit·Bash·PowerShell)](https://code.claude.com/docs/en/permissions),
[설정 파일 위치·우선순위](https://code.claude.com/docs/en/settings),
[설정 키 목록·sandbox 경로 규칙·`env` 제한](https://code.claude.com/docs/en/settings-reference),
[sandbox(플랫폼 지원·네트워크·credentials·SSH git)](https://code.claude.com/docs/en/sandboxing),
[환경변수(`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`)](https://code.claude.com/docs/en/env-vars),
[설정 JSON 스키마](https://json.schemastore.org/claude-code-settings.json).

## 이번 검증 결과

| 항목 | 결과 |
|---|---|
| `.claude/settings.json` JSON 문법 | 통과 |
| 공개 JSON 스키마(schemastore) 검사 | 오류 0건 |
| `claude doctor`(v2.1.319) | 설정 오류 없음. 설정과 무관한 중복 설치 경고 1건 |
| `.gitignore`가 `.claude/settings.json`을 제외하는지 | 제외하지 않음(커밋 가능) |
| `scripts/sync_skills.py --check` | 통과. 이 스크립트는 `.claude/skills`만 다룬다 |
| 작업 세션의 Read 도구로 없는 `.env.canary` 열기 | 접근 거부(규칙 로드 확인) |
| 작업 세션의 Bash `cat .env.canary` | 접근 거부 |
| 가짜 파일이 있는 상태의 새 세션 검사 | 미실행. 위 확인 순서대로 사용자가 진행 |
| sandbox OS 차단 | 미실행. 공유 설정에서 꺼져 있음 |

검사는 존재하지 않는 경로로만 해서 거부가 파일 내용을 읽기 전에 일어났는지 확인했다.
`printenv`·`env` 거부는 규칙이 빠졌을 때 실제 환경변수가 출력될 수 있어서 시험하지 않았다.
실제 `.env`·`.env.example`·전역 설정·SDK 인증 프로필은 열지 않았고 API 호출은 하지 않았다.
Python 코드를 바꾸지 않아 `make check`는 실행하지 않았다.
