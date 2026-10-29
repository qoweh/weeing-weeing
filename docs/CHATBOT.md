# 챗봇 계약과 후속 연결

상위 [#85](https://github.com/qoweh/weeing-weeing/issues/85), 이번 범위
[#86](https://github.com/qoweh/weeing-weeing/issues/86)(① 공통 계약·인터페이스).
현재는 데이터 검증과 Protocol만 추가했으며 실행 가능한 챗봇 API·화면은 없다.
정확한 계약은 [CONTRACTS](CONTRACTS.md)의 챗봇 절을 따른다.

## 첫 단계 사용 예

```python
from uuid import uuid4

from weeing_weeing.contracts import ChatQuestion, ChatSearchConditions

question = ChatQuestion(
    request_id=uuid4(),
    question="입구 센서 장기 점유의 매뉴얼 기준과 과거 사례를 알려줘",
    conditions=ChatSearchConditions(asset_id="BLDC-001", limit=5),
)
```

질문 의도는 서버가 분류하며, 클라이언트의 사용자 ID·과거 대화·권한 지정은 받지 않는다.
검색 조건은 권한을 부여하지 않는다. API가 기존 보고서 원문 권한과 대화 소유권을
검사하고 제한된 검색기를 서비스에 주입한다. 대화 재조회 때도 출처 권한을 다시 검사한다.

## 후속 API 제안 (#90·#91, 미구현)

기존 인증과 동일한 Bearer 토큰을 사용한다. 요청 사용자 ID는 인증 세션에서 얻는다.

| 경로 | 요청·결과 제안 |
|---|---|
| POST /chat/conversations | 빈 대화 생성 → ChatConversation |
| GET /chat/conversations | 내 대화 목록 → ChatConversation 목록(페이지 처리 후속 정의) |
| GET /chat/conversations/{id} | 내 대화·메시지 재조회, 출처 권한 재검사 |
| POST /chat/conversations/{id}/messages | ChatQuestion → 단일 ChatResponse |
| POST /chat/conversations/{id}/messages/{request_id}/feedback | 본인 응답 피드백. 세부 계약은 #90에서 정의 |

`request_id`는 한 대화 내 중복 전송 식별자다. 동일 ID·동일 질문은 저장 응답을 반환하고,
같은 ID의 다른 본문은 409로 거부하는 방식을 제안한다. 실패 후 재실행 정책과 동시 요청
잠금은 #90에서 정한다. API 입력 검증 422, 미인증 401, 소유권·원문 권한 실패 403,
대화 없음 404, 충돌 409를 제안한다. 서비스 실행 실패는 FAILED와 오류 코드를 사용하고
HTTP 429/502/503/504 매핑은 #91에서 확정한다. 공급자 키 오류를 401로 반환하지 않는다.

## 실행·제한 정책 제안 (#89·#91, 미구현)

공용 LLM은 #101/#107에서 Claude로 전환됐다. `get_llm_client()`와 기존
`LlmClient.generate_json()`을 그대로 재사용하며 별도 공급자 어댑터를 만들지 않는다.
현재 출력 상한은 공용 Claude 구현의 16000토큰이고 타임아웃·재시도는 SDK 설정을 따른다.
아래 1024토큰·전체 시간 예산은 챗봇의 후속 제안이며 현재 구현된 제한으로 간주하지 않는다.
현재 인증/연결 실패는 같은 `LlmUnavailableError`, 429/5xx는 일반 `LlmError`로 전달된다.
세부 오류 매핑·전체 시간 예산·재시도 정책은 #89에서 공용 클라이언트와 함께 보완한다.

- API 수명주기에서 검색 모델·저장소·공급자 HTTP 클라이언트를 만들고 재사용한다.
- 동기 ChatService와 검색·임베딩·LLM은 제한된 작업 스레드에서 실행해 이벤트 루프를
  막지 않는다. 스레드 대기를 취소해도 내부 호출이 멈추는 것은 아니므로 HTTP 타임아웃과
  단계별 남은 시간 확인을 함께 구현한다. 같은 DB 세션을 스레드 간 공유하지 않는다.
- 전체 처리 60초, 검색 10초, LLM은 남은 시간 이내, 연결 5초를 초기 제안으로 둔다.
  전체 예산은 큐 대기·재시도·대기를 포함한다. 출력 1024토큰, 서버 동시 생성 2개,
  재시도 최대 1회로 시작하되 #89·#91 구현·평가에서 설정값을 확정한다.
- 타임아웃·429·일시 장애만 남은 예산 내에서 제한적으로 재시도한다. 인증·잘못된 요청은
  자동 재시도하지 않는다. 서비스 장애를 근거 부족으로 숨기거나 로컬 LLM으로 우회하지 않는다.
- 계약 상한: 질문 2000자, 최근 대화 20개·각 4000자·총 16000자, 검색 20개.
  토큰 한도는 별도로 구현하며 최근 대화만 공급자에 보낸다.
- 이번 단계의 응답에는 LLM 사용량 필드를 두지 않는다. #89·#90에서 기존 `LlmUsage`의
  재사용·변환과 요청 ID별 저장 방식을 결정한다. 공급자·모델·입출력 토큰·지연·시도 수
  수집과 SDK 재시도·실패 사용량 추적은 후속 범위다. 공유 `last_usage`의 동시 호출 경합을
  방지하고 키·전체 프롬프트·개인정보를 로그에 남기지 않는다. FAQ 직접 응답은 LLM을 호출하지 않는다.

## 후속 작업

② #87 FAQ·분류 → ③ #88 허용 근거 검색 → ④ #89 상용 LLM·응답 검증 →
⑤ #90 저장 → ⑥ #91 API → ⑦ #92 hmi/web → ⑧ #93 통합 평가 순이다.
⑤는 ① 이후 독립 진행할 수 있다. 공용 LLM 전환 #101은 완료됐으며 #89는 기존 Claude
클라이언트를 연결하고 챗봇 응답 검증·사용량 수집·호출 제한을 구현한다.
#74 관련도 정책·#75 평가·#76 청킹은 담당 이슈에서 처리한다.

이번 단계 검증은 `uv run --no-sync pytest tests/contracts tests/agent`와 `make check`다.
실제 상용 API E2E·DB·HMI 실행 검증은 연결 구현 후 각 이슈에서 수행한다.
