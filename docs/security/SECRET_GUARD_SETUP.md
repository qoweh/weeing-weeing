# API 키를 사용하기 전 읽기 차단 확인

작성일: 2026-11-03. 실제 `.env`와 `.codex/config(1).toml`은 열지 않는다.

## 이번에 준비한 설정

> 2026-11-10(#375): Codex 설정(`.codex/`)은 저장소에서 빼고 `.gitignore`에 넣었다.
> Codex를 쓰는 사람은 아래 규칙을 개인 `.codex/config.toml`에 직접 둔다. 이하는 작성 당시 기록이다.

`.codex/config.toml`에 실제 키가 없는 보호 설정을 두고, 새 Codex 세션에서
`weeing-secret-guard` 권한 프로필을 선택한다.
기존 `config(1).toml`은 읽거나 덮어쓰거나 이름을 바꾸지 않는다.

- 경로는 작업 폴더 기준(`:workspace_roots`)이라 저장소를 어디에 받아도 macOS·Windows에서 같이 쓴다.
- 작업 폴더 루트의 `.env`·`.env.*`(가짜 `.env.canary` 포함)와 하위 폴더의 `.env`·`.env.*`를 차단한다.
- `C:/weeing-weeing/.env`와 가짜 `.env.canary`는 기존 절대 경로 차단도 유지한다.
- `.claude/worktrees/<이름>`을 작업 폴더로 열면 상대 경로 규칙만으로는 본 저장소 루트의 `.env`(3단계 위)를 차단하지 못한다.
  위 절대 경로는 `C:/weeing-weeing`을 보호한다. 다른 위치에서는 본 저장소 루트에서 Codex를 열거나 개인 전역 설정에 자기 절대 경로를 따로 추가한다. Codex는 `../` 경로를 받지 않는다.
- 과거 키를 넣었던 `.env.example`도 차단 대상에 포함한다.
- Codex 명령에 키·토큰 환경변수가 상속되는 것을 줄인다.
- Codex가 실행하는 셸 명령의 네트워크를 끈다.
- IDE 자동 문맥, 별도 앱·커넥터, 사용자 터미널에는 별도 설정이 필요하다.

## 쉬운 확인 순서

1. 실제 키를 넣지 않은 상태를 유지한다.
2. 설치 후 Codex를 종료하고 같은 폴더에서 새 세션을 연다.
   Windows 샌드박스 설치 안내가 나오면 `elevated` 설정의 관리자 승인 절차를 완료한다.
   이는 Codex를 항상 관리자 권한으로 실행하라는 뜻이 아니다.
   설치 안내가 없다면 일반 사용자 터미널에서 `codex`를 실행하고
   `/setup-default-sandbox` 안내를 확인한다. 정책에 의해 설치가 막히면 관리자에게 요청한다.
3. 권한 선택 메뉴에 `weeing-secret-guard`가 표시되는지 확인하고 선택한다.
   메뉴에서 선택할 수 없거나 설정 오류가 나오면 적용 완료로 보지 않는다.
4. 새 세션에 다음과 같이 요청한다.

   > 가짜 `.env.canary`만 읽기 차단을 재검사해줘. 내용은 출력하지 말고
   > 읽기 성공·접근 거부만 알려줘. 실제 `.env`와 `config(1).toml`은 읽지 마.

5. 정상 소스 파일은 읽을 수 있고 가짜 파일은 접근 거부되어야 한다.
   파일 없음·도구 시작 실패·설정 오류는 읽기 차단 성공이 아니다.
   셸 검사만 했다면 파일 직접 읽기 도구까지 검증했다고 기록하지 않는다.

전역·관리형 설정에 기존 `sandbox_mode`가 있으면 새 프로필 선택에 영향을 줄 수 있다.
전역 인증·설정 파일의 내용을 채팅에 보내지 않는다. 관리형 제한이 새 프로필을 허용하지
않거나 Windows에서 셸 읽기를 막지 못하면 관리자 설정 또는 별도 OS 계정·권한 구성이
필요하다. 이 문제를 피하려고 전체 접근 권한이나 샌드박스 해제를 선택하지 않는다.

## macOS에서 확인

macOS는 Seatbelt로 차단하고 `[windows]` 설정은 무시한다. 관리자 승인 절차는 없다.

1. 저장소 루트에 가짜 `.env.canary`를 만든다. 실제 키를 넣지 않는다.
2. 사용자 터미널에서 저장소 루트로 이동해 다음을 실행한다.

   ```bash
   codex sandbox -P weeing-secret-guard -- cat README.md >/dev/null; echo $?
   codex sandbox -P weeing-secret-guard -- cat .env.canary >/dev/null; echo $?
   ```

3. 첫 줄은 `0`, 둘째 줄은 `Operation not permitted`와 `1`이 나와야 한다.
   `default_permissions requires a [permissions] table` 오류가 나오면 프로젝트 설정이
   로드되지 않은 것이다. 신뢰된 프로젝트인지 확인하고, 차단 성공으로 보지 않는다.
4. 이어서 위 "쉬운 확인 순서" 4~5단계로 Codex 세션의 파일 읽기 도구도 확인한다.

Claude Code용 같은 설정은 [CLAUDE_SECRET_GUARD_SETUP.md](CLAUDE_SECRET_GUARD_SETUP.md)를 따른다.

## 실제 API 실행

가짜 파일 검증 후에도 IDE 자동 문맥 끄기, 비밀 파일 탭 닫기, Git 제외,
가짜 키로 로그 마스킹 검사를 별도로 확인한다. 실제 인증 확인과 유료 LLM 실행은
사용자가 자기 터미널에서 수행한다. Codex는 실제 `.env`를 로드하지 않는다.
사용자가 실행하는 프로그램에는 `.env` 읽기 권한이 필요하다.
위 Codex 프로필의 네트워크 제한은 사용자 터미널의 실행 설정이 아니다.

설정 파일 설치만으로 보호 완료를 선언하지 않는다. 새 세션에서 적용 여부와
각 읽기 경로의 결과를 기록한 뒤 실제 키 사용 여부를 판단한다.

근거: [공식 권한 프로필](https://learn.chatgpt.com/docs/permissions),
[프로젝트 설정](https://learn.chatgpt.com/docs/config-file/config-basic),
[Windows 보안과 가짜 파일 검증](https://learn.chatgpt.com/docs/enterprise/security-cookbook),
[Windows 샌드박스 설치](https://learn.chatgpt.com/docs/windows/windows-sandbox).

## macOS 검증 결과 (2026-11-06, codex-cli 0.166.0)

저장소 밖 임시 폴더에 같은 설정과 가짜 파일만 두고 `codex sandbox`로 시험했다.
실제 `.env`·전역 설정은 열지 않았다.

| 항목 | 결과 |
|---|---|
| `README.md` 읽기 | 성공 |
| 가짜 `.env.canary`·하위 폴더 가짜 `.env.local` 읽기 | `Operation not permitted`. 차단 성공 |
| 네트워크(`curl`) | 이름 해석 실패. 차단 성공 |
| `.claude/worktrees/<이름>`을 루트로 열고 상위 가짜 `.env.canary` 읽기 | 읽기 성공. 위 제한 사항 확인 |
| Windows elevated 환경 재검사 | 미실행. Windows 사용자가 위 순서로 확인 필요 |

## 이번 검증 결과 (2026-11-03, Windows)

| 항목 | 결과 |
|---|---|
| 새 설정의 TOML 문법·필수 차단 규칙 | 통과 |
| `.codex/config.toml` 설치 | 생성. 기존 `config(1).toml`은 미열람·미변경 |
| 현재 대화의 셸 읽기 | 가짜 `.env.canary` 읽기 성공. 차단 실패 |
| 일반 소스 파일 읽기 | `README.md` 읽기 성공 |
| 별도 CLI에서 새 프로필 선택 | 프로젝트 설정 로드 오류. 이 경로의 프로필 활성화 미확인 |
| 규칙을 명시한 Windows 샌드박스 시험 | `Restricted read-only access requires the elevated Windows sandbox backend` 오류. 시험 프로세스 미실행 |
| 대체 MXC 시험 | `native MXC is unavailable on this executor` 오류. 시험 프로세스 미실행 |
| 최종 보호 상태 | 미완료. 사용자 Windows 샌드박스 설치·새 세션 적용 후 재검사 필요 |

별도 CLI에서 명시한 시험 규칙은 실제 `.env`와 가짜 `.env.canary`를 deny 대상으로
지정했지만, 읽기 대상은 가짜 파일과 README로만 제한했다. 실제 `.env`는 열지 않았다.
보호를 우회하려고 가짜 파일 검사를 샌드박스 밖으로 승격하지 않았다.
실제 키·SDK 인증 프로필·`config(1).toml`·전역 설정 파일 내용은 열지 않았다.
API 호출은 하지 않았다. 프로그램 코드는 변경하지 않았다.

전체 `make check`는 이번에 실행하지 않았다. 기존 `tests/test_config.py`가
`.env.example` 내용을 실제로 읽는데, 해당 파일은 과거 실제 키가 입력됐던 경로이고
이번 보호 설정에서도 차단 대상이다. 보호 대상 내용을 읽지 않도록 이번 검증은
새로 작성한 설정의 문법·설치본 일치·가짜 파일 접근 검사로 제한했다.
