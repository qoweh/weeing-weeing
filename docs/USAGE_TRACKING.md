# LLM 사용량 기록 (Langfuse)

Claude API는 토큰만큼 과금되는데 팀원 6명이 각자 호출하고, 키를 우리가 발급하지 않아 콘솔 사용량 화면도 볼 수 없다. 그래서 **모든 LLM 호출을 홈서버의 Langfuse에 기록**해 사람별·기능별·모델별 토큰과 비용을 본다. 이슈 #113, 결정 D-27.

## 구조

```mermaid
flowchart LR
  pc["팀원 PC<br/>ClaudeClient"] -- "LLM 호출" --> anth["Anthropic API"]
  pc -- "사용량 기록(HTTPS, 백그라운드)" --> cf["Cloudflare<br/>(Tunnel·Access)"]
  web["팀원 브라우저"] -- "대시보드(이메일 인증)" --> cf
  cf --> lf["홈서버 Langfuse"]
```

- LLM 호출은 지금처럼 각자 PC에서 Anthropic으로 바로 간다. 홈서버는 기록만 받는다.
- **홈서버가 꺼져 있어도 분석·챗봇은 그대로 된다.** 기록만 빠지고, 스크립트가 끝날 때 몇 초 기다린 뒤 경고를 남긴다.
- 서버 운영(구축·키 발급·단가 등록)은 김민우 담당.

## 무엇을 남기나

| 기록 | 언제 | 담는 것 |
|---|---|---|
| trace (`agent`) | 에이전트 실행 1번(`make analyze`, 사건 분석) | 사람(`user_id`), 사건 ID(`session_id`), 태그(진입점·프롬프트 버전), 반복 횟수·도구 호출 수·토큰 합계 |
| generation (`claude`) | LLM 호출 1번 | 모델(대체 모델이 답했으면 실제 모델), 입력·출력·캐시 읽기·캐시 쓰기 토큰, 시간, `stop_reason`, effort, 오류 |
| tool | 도구 호출 1번 | 도구 이름, 입력 오류면 WARNING |

- **태그(진입점)**: `analyze`, `llm-check`, 기본값 `app`. 새 기능에서 `get_llm_client(entrypoint="chatbot")`처럼 이름을 주면 기능별로 나뉜다.
- **본문은 기본으로 보내지 않는다.** 프롬프트·응답·도구 입력은 `LANGFUSE_CAPTURE_CONTENT=true`일 때만 보낸다. 디버깅할 때만 켠다.
- API 키, 사번·결재 정보는 어떤 경우에도 보내지 않는다.

## 팀원 설정 (한 번만)

진행 상황과 완료 체크는 공지 이슈 #115에서 한다.


1. 최신 `dev`를 받고 `uv sync --locked --no-install-project`
2. 김민우에게 **본인 전용** Langfuse 키(공개 키·비밀 키)와 서버 주소를 개별로 받는다
3. `.env`에 넣는다(커밋 금지, 화면 공유·로그에 노출 금지)
   ```bash
   LLM_USER=<본인 GitHub 핸들>
   LANGFUSE_BASE_URL=https://langfuse.<도메인>
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   ```
4. 대시보드: 서버 주소에 접속 → Cloudflare 이메일 코드 인증 → Langfuse 가입(처음 한 번) → 김민우가 프로젝트에 초대
5. 확인: `make analyze`를 한 번 실행하고 1분 안에 Langfuse Traces에 본인 `user_id`로 기록이 보이면 끝

기록이 안 보이면 다음을 차례로 확인한다.
- 터미널에 `Langfuse` 경고가 찍혔는지
- `LANGFUSE_BASE_URL`에 `https://`까지 들어 있는지
- 브라우저로 `<주소>/api/public/health`가 열리는지

## 비용을 아끼는 약속

- 개발 중에는 `LLM_MODEL=claude-sonnet-5-5` 또는 `claude-haiku-5-5`를 쓰고, Opus(기본값)는 평가·시연 때 쓴다.
- 반복 실행·루프 테스트는 가짜 LLM(테스트)으로 한다. 실제 API는 확인이 필요할 때만 부른다.
- 시연·평가처럼 구분해서 보고 싶으면 `LANGFUSE_TRACING_ENVIRONMENT=demo`처럼 환경 이름을 바꾼다.

## 단가 등록 키 (서버 관리자용)

비용은 Langfuse에 등록한 모델 단가로 계산한다. 코드가 보내는 토큰 이름이 아래와 같으므로 단가도 같은 이름으로 등록한다.

| usage 키 | 뜻 |
|---|---|
| `input` | 캐시가 아닌 입력 토큰 |
| `output` | 출력 토큰(생각 단계 포함) |
| `cache_read_input_tokens` | 프롬프트 캐시에서 읽은 입력 |
| `cache_creation_input_tokens` | 프롬프트 캐시에 쓴 입력 |

## 아직 안 한 것

- **호출을 막는 예산 상한은 없다.** 기록은 사후에 보는 것이다. 1~2주 기록을 보고 필요하면 홈서버에 LLM 게이트웨이(팀원별 가상 키와 예산)를 두는 방법을 따로 정한다.
- API 서버(`make api`)·챗봇은 `get_llm_client`를 쓰면 자동으로 기록된다. 다만 오래 떠 있는 프로세스라 따로 flush하지 않아도 SDK가 주기적으로 보낸다.


## 챗봇 호출 통계 (#89)

대화 도구 루프와 최종 답변 근거 대조는 동일 tracer로 연결된다. 검토용 Claude 호출도
별도 generation이므로 호출 수·토큰에 포함된다. CLI는 last_run의 request_id를 대조하고
호출별 통계를 읽는다. 실제 응답 모델이 있으면 요청 모델 대신 기록한다.
공급자 usage가 없거나 요청이 실패해 사용량을 확인하지 못하면 None이며 합계를 0으로
대신하지 않는다. 재시도 내부의 실제 과금/사용량은 SDK 응답만으로 알 수 없을 수 있다.
Langfuse 자체 오류 및 관측된 예외는 예외 종류만 기록하고 원시 오류 본문은 전송하지 않는다.
