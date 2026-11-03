# 챗봇 HTTP API (#91)

`api/chat.py`를 기존 FastAPI 앱에 연결했다. FAQ 버튼 선택과 자유 질문 전송은 서로 다른
경로를 사용한다. JSON API를 `frontend` 대시보드의 챗봇 패널에 연결했으며 스트리밍은 포함하지 않는다.

## 인증·접근 범위

기존 `POST /auth/login`의 access_token을 `Authorization: Bearer <토큰>`으로 보낸다.
모든 /chat 경로에 로그인이 필요하다. 사용자 ID는 서버가 세션에서 얻는다.
대화 목록·조회·변경·삭제·전송·요청 상태 확인은 본인만 가능하고 관리자도 예외 없다.
타인 대화와 없는 대화는 동일 404다. 성공 응답은 Cache-Control: no-store를 사용한다.

## 경로

| 메서드·경로 | 입력·결과 |
|---|---|
| GET /chat/faq/topics | 활성 주제 목록(FaqTopic[]) |
| GET /chat/faq/topics/{topic_id}/questions | 주제의 선택 질문 목록(FaqQuestion[]) |
| POST /chat/conversations | {title?, conditions?} → 새 FAQ 모드 대화(201) |
| GET /chat/conversations | 본인 대화 목록. limit=50(1~100), offset=0 |
| GET /chat/conversations/{id} | 대화·메시지 페이지. after_sequence=0, limit=100(1~200) |
| PATCH /chat/conversations/{id} | {title?, conditions?, mode?} → 변경된 대화 |
| DELETE /chat/conversations/{id} | 본인 대화·연결된 요청/메시지 삭제(204) |
| POST /chat/conversations/{id}/faq-selections | FaqSelection → ChatRequestView |
| POST /chat/conversations/{id}/messages | ChatQuestion → ChatRequestView |
| GET /chat/conversations/{id}/requests/{request_id} | 요청 상태·저장 응답(ChatRequestView) |

변경할 항목만 PATCH로 보낸다. null·소유자 변경은 허용하지 않는다.
처리 중에는 같은 대화의 다른 요청·모드/조건 변경이 409다.
FAQ 목록은 프로세스에서 검증한 동일 스냅샷을 재사용한다. FAQ 파일 배포 후 서버를 재시작한다.

## 버튼 선택 → 답변

1. POST /chat/conversations에 `{}`를 보내 conversation_id를 얻는다(FAQ 모드).
2. 주제 → 세부 질문 목록을 조회해 버튼을 구성한다.
3. 버튼 선택 시 목록의 FAQ ID와 새 요청 UUID를 보낸다.

```json
{
  "request_id": "4a8ef8c4-00e6-486c-b0c6-cb59136126e3",
  "faq_id": "FAQ-ACCESS-001"
}
```

question·kind는 보내지 않는다. 서버가 선택 FAQ를 검증하고 대표 질문·답변·출처를 저장한다.
검색 모델·Claude·API 키 없이 처리된다. 이미 저장된 선택은 FAQ 파일이 바뀌어도 당시 답변을 반환한다.
없는/비활성 FAQ는 FAQ_NOT_FOUND(404)다. 목록을 새로 받은 뒤 새 ID로 선택한다.
FAQ 수동 버전·검토일·참고 문서 필드는 요청/응답에 없으며 선택 ID의 현재 답변을 사용한다.
FAQ 오류 때문에 LLM을 자동 호출하지 않는다.

## 채팅 시작 → 자유 질문

‘채팅 시작’ 버튼을 누르면 해당 대화에 아래 PATCH를 보낸다.

```json
{"mode": "CHAT"}
```

그 뒤 /messages로 질문을 보낸다. mode 전환 없이 자유 질문을 보내면 409다.

```json
{
  "request_id": "1d4adf41-e033-4eb4-ad69-01a183af7689",
  "question": "P03 입구 센서 점검 절차를 알려줘"
}
```

conditions를 생략하면 대화에서 선택한 조건을 유지한다. 조건을 바꾸려면 PATCH로 먼저 갱신한다.
명시한 conditions는 대화 조건과 같아야 한다. 자유 질문은 기존 검색기·Claude·응답 검증을 사용하므로
DB·색인·사용자 로컬의 Claude 인증 설정이 필요하고 실제 비용이 발생한다.
CHAT 모드에서도 /faq-selections로 FAQ를 선택할 수 있다.

## 결과와 중복 전송

전송·요청 상태 조회는 ChatRequestView를 반환한다. 다음은 일부 필드 예시다.

```json
{
  "state": "COMPLETED",
  "retry_allowed": false,
  "response": {
    "status": "OK",
    "message": "검토된 FAQ 답변입니다.",
    "parts": [{"kind": "FAQ", "text": "답변 본문", "source_ids": ["faq:example"]}],
    "sources": [{"kind": "FAQ", "source_id": "faq:example", "title": "FAQ 안내", "faq_id": "FAQ-ACCESS-001"}]
  }
}
```

예시는 축약본이다. 전체 필드는 /docs에서 확인한다.
화면은 response.message, response.parts[].text, response.sources를 표시한다.
**state=COMPLETED는 응답 저장 완료**다. response.status가 FAILED·NEEDS_CLARIFICATION·
INSUFFICIENT_EVIDENCE인지도 확인해 각각 오류·추가 질문·근거 부족으로 표시해야 한다.

| 상태/상황 | HTTP·클라이언트 처리 |
|---|---|
| COMPLETED | 200, 저장 응답 표시. 응답 자체가 FAILED여도 200이며 자동 재생성하지 않음 |
| RESERVED / RUNNING | 202, response=null. Retry-After(1초) 후 Location으로 GET |
| 실행 전 준비 실패·실행 전 예약 만료 | 503, retry_allowed=true일 때만 명시적 재시도 가능 |
| FAQ_NOT_FOUND | 404, 목록 새로고침 후 새 ID로 선택 |
| UNKNOWN | 409, 결과·과금 여부 불명. 같은 ID 재실행 불가 |
| 같은 ID 다른 본문·처리 중 모드 변경 | 409, detail 안내 |
| 로그인 없음·무효 토큰 | 401 |
| 잘못된 입력·식별자·범위 | 422 |
| DB·FAQ 카탈로그 장애 | 503, 안전한 detail 안내 |

전송의 ID는 질문/선택 1회마다 새 UUID를 만들고 네트워크 재전송에는 기존 ID를 유지한다.
같은 ID·같은 본문은 새 실행 없이 현재 상태/저장 응답을 반환한다.
저장된 결과는 FAQ 카탈로그·검색기·Claude 연결에 장애가 있어도 반환한다.
실행 전 실패에 대한 재실행은 같은 전송 경로에 `?retry=true`를 명시한다.
503을 받았다고 무조건 재전송하지 말고 우선 요청 상태를 조회해 실제 상태를 확인한다.
state가 없는 오류 응답은 기존 API와 동일한 {detail: ...} 형태다.
공급자 인증 오류는 로그인 401로 반환하지 않으며 저장 응답의 failure에서 확인한다.

## 직접 확인

개발 DB를 준비한 사용자 터미널에서 실행한다.

```sh
make api
```

1. http://localhost:8000/docs 를 연다.
2. POST /auth/login에 본인 계정을 입력해 로그인한다.
3. 반환된 access_token을 오른쪽 Authorize의 HTTPBearer 입력칸에 넣는다(토큰 값만 입력).
4. 위 순서로 대화 생성 → FAQ 목록/선택 → CHAT 모드 변경 → 질문 전송을 실행한다.
5. 반환된 response와 GET 대화/요청 상태에서 저장 결과를 확인한다.

FAQ는 키 없이 확인할 수 있다. 자유 질문의 실제 Claude 호출은 사용자가 자기 터미널에서
인증을 준비한 뒤 실행한다. 토큰·키를 소스·질문·스크린샷·채팅에 붙이지 않는다.
기존 CLI는 HTTP 로그인/저장에 연결하지 않았으므로 HTTP와 별도의 메모리 대화다.

자동 검증은 키·실제 DB 없이 실행한다.

```sh
UV_NO_ENV_FILE=1 uv run --no-sync --no-env-file pytest -q tests/api/test_chat_http.py
UV_NO_ENV_FILE=1 make check
```

## 대시보드 화면 (#92)

실제 로그인·보고서 화면이 있는 `frontend`에 연결한다. `hmi/web`에는 중복 구현하지 않는다.

- 챗봇을 열면 FAQ 주제 → 세부 질문 → 선택 답변 순으로 탐색한다. 답변은 서버의 FAQ ID로
  조회하며 프론트에 FAQ 답변을 하드코딩하지 않는다. FAQ 장애 시 자동으로 LLM을 호출하지 않는다.
- 하단의 **채팅 시작**은 목록·질문·답변 상태에서 항상 보인다. 버튼은 대화의 CHAT 모드만
  갱신하며 실제 질문 전송 전에는 LLM을 호출하지 않는다. 기존 FAQ 대화도 유지한다.
- 하나의 답변 말풍선에 parts의 본문을 문단으로 이어 보여주고, 내부 intent 라벨은 표시하지 않는다.
  추가 확인·근거 부족은 서버의 구체적 설명/질문을, 장애는 오류 종류별 안내를 표시한다.
- 선택한 설비·모델·조치일은 패널 위 검색 조건에서 변경한다. 빈 값은 전체 범위이며 잘못된
  날짜 순서는 전송 전에 거부한다. 모델 조건은 정비이력에서 지원하지 않고 기간은 매뉴얼에서 지원하지 않는다.
- 내 대화 목록·새 대화·기존 대화 복원은 인증 API를 사용한다. 메시지는 서버 페이지를 순서대로
  읽으며 브라우저의 별도 영구 저장소에 복사하지 않는다. 로그아웃 시 패널을 초기화하고 상태 조회를 중단한다.
- 한 질문에 요청 UUID 하나를 사용한다. 연속 클릭을 잠그고 전송 결과를 잃으면 GET 상태 확인만
  제공한다. RESERVED/RUNNING은 GET으로 확인하며, 서버가 retry_allowed=true로 허용한 실행 전
  실패만 같은 ID·같은 본문으로 명시 재시도한다. UNKNOWN은 자동/같은 ID 재실행을 하지 않는다.
  요청 상태 없는 409·422 등 명확한 접수 거절은 전송 잠금을 해제하고 질문 초안을 복원한다.
  409는 서버 대화 모드·기존 요청을 다시 조회하며 새 질문을 자동 재전송하지 않는다.
- 출처의 매뉴얼은 `GET /documents/original?doc_id=...&doc_version=...`로 인증 조회한다.
  현재 등록 판·파일 SHA-256을 확인하며 data 또는 업로드 폴더 밖의 파일은 반환하지 않는다.
  인용 판이 삭제/교체됐으면 404로 안내하고 최신 파일로 조용히 대체하지 않는다.
- 보고서 출처는 기존 버전 조회 API로 인용 판의 원문 내용을 읽기 전용으로 연다. 생성한 샘플 PDF를
  자동 제공하는 기능은 아니다. 서버가 내려준 임의 URL/HTML을 실행하거나 외부 링크로 열지 않는다.
- 피드백 저장·서버 전체 생성 제한·외부 호출 취소 보장은 이번 범위가 아니며 #142 등 후속 범위다.

프론트 검증: `cd frontend && npm run test:chat && npm run build`.
`npm run dev`로 실행한 뒤 `http://localhost:3100`에서 로그인하고 챗봇 버튼을 연다.
백엔드는 기존 `make api`로 실행한다. 자유 질문은 사용자가 서버 인증 설정을 준비한 뒤 직접 실행한다.
FAQ·내 대화 조회에는 Claude 키가 필요 없다. API 키를 브라우저에 입력하거나 저장하지 않는다.


## 챗봇 현재 주의·경고 조회

기존 채팅 메시지 API에서 Claude가 `query_incidents`를 선택하면 DB 사건을 조회한다.
응답에 `intent/parts.kind=INCIDENT`, `sources.kind=INCIDENT_QUERY`가 추가된다.
조회 시각과 전체 집계 건수를 출처에 표시한다. 목록 상한은 챗봇 근거 전달에만 적용한다.
화면 상단 알림은 기존 사건 목록 API와 30초 갱신을 유지한다.

## 마크다운 및 검증 후 SSE 전송

웹 자유 질문은 `POST /chat/conversations/{conversation_id}/messages/stream`을 사용한다.
본문·Bearer 인증·retry 규칙은 기존 `/messages`와 같다. FAQ는 기존 JSON 경로를 유지한다.
응답은 `text/event-stream`, `Cache-Control: no-store`, `X-Accel-Buffering: no`다.

1. progress의 phase로 같은 상태 문구를 갱신한다. 생성→검색→생성→검토처럼 반복될 수 있다.
2. 검증·DB 저장 완료 전에는 본문을 전송하지 않는다. 완료된 OK 본문만 delta.text로 이어 붙인다.
3. done.request로 최종 상태·본문·출처를 확정하고 기존 기록 조회로 복원한다.

이는 공급자 생성 토큰을 즉시 공개하는 방식이 아니라 **검증 후 전송 스트림**이다.
답변 검증까지의 지연은 유지한다. 서버는 지연 없이 전송하고, 화면은 검증된 본문을
최대 6초 동안 순차 표시한다. 모션 줄이기 설정에서는 이 효과를 생략한다.
헤더 전송 전 인증·소유권 오류는 기존 401/404, 전송 시작 뒤 오류는 error 이벤트로 전달한다.
연결 중단·오류 시 같은 요청 ID의 기존 GET 상태 확인을 사용하며 POST를 자동 재전송하지 않는다.
중복 요청은 저장 응답을 재전송할 뿐 LLM을 다시 호출하지 않는다. 연결 종료는 생성 취소가 아니다.
배포 프록시도 SSE 응답을 버퍼링하지 않도록 설정해야 한다.

웹 답변과 과거 기록에는 마크다운 제목·목록·강조·표·코드 블록을 적용하고,
본문에 작성된 한 번 개행도 실제 줄바꿈으로 보존한다. 원시 HTML·외부
이미지 로드는 차단하며, 원문은 기존 문서/보고서 출처 버튼으로 연다.
