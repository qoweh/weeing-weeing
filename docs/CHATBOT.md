# 챗봇 계약과 후속 연결

상위 [#85](https://github.com/qoweh/weeing-weeing/issues/85), 공통 계약은
[#86](https://github.com/qoweh/weeing-weeing/issues/86), 파일 기반 FAQ 선택 조회는
[#87](https://github.com/qoweh/weeing-weeing/issues/87)의 범위다.
FAQ 조회와 자유 대화 도구 루프를 구현했으며 챗봇 HTTP API·실사용 검색 연결·화면은 아직 없다.
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

자유 질문은 별도 사전 분류 없이 Claude의 도구 호출 흐름으로 전달한다.
클라이언트의 사용자 ID·과거 대화·권한 지정은 받지 않는다.
문서 원문은 로그인 사용자에게 공통 열람한다. 보고서의 초안·반려·과거 판도 포함한다.
API는 로그인·본인 대화 소유권을 검사하고 조건·출처 상태 검증 검색기를 주입한다.
대화 재조회 때는 본인 소유권과 인용 문서의 삭제·개정 상태를 확인한다.
보고서 작성·수정·제출·결재 권한은 문서 열람과 별개이며 기존 규칙을 유지한다.

## FAQ 주제·질문 선택 (구현)

챗봇을 열면 **주제→세부 질문→검토 답변**을 탐색한다. FAQ ID로 선택하므로
의도 분류·문장 매칭·임베딩·LLM을 호출하지 않는다. **채팅 시작** 버튼은 주제 목록,
질문 목록, FAQ 답변을 보는 동안 항상 표시한다(#92 화면 후속 구현).
버튼으로 전환한 후에만 자유 입력창을 열고, 실제 질문 전송 때 자유 대화 경로를 호출한다.
버튼 클릭 자체로 검색·LLM을 실행하지 않는다.

저장소 루트에서 `PYTHONPATH=src uv run --no-sync python`을 실행한 뒤 다음 예제로
조회할 수 있다. 프로젝트 자체를 설치하지 않으므로 직접 실행 시 src 경로가 필요하다.

```python
from uuid import uuid4

from weeing_weeing.agent.interface import load_faq_catalog
from weeing_weeing.contracts import FaqSelection

catalog = load_faq_catalog()
topics = catalog.list_topics()
questions = catalog.list_questions(topics[0].topic_id)
question = questions[0]
snapshot = catalog.get_answer(question.faq_id)
response = catalog.answer(
    FaqSelection(
        request_id=uuid4(),
        faq_id=question.faq_id,
        faq_version=question.faq_version,
    )
)
# snapshot.question / snapshot.answer: 서버 데이터로 저장할 질문·답변
# response.parts[0].text: 그대로 표시할 검토 답변
```

API 키·DB·모델 다운로드 없이 동작한다. API 구현 시 일반 이용 안내 FAQ도 기존 인증
정책에 맞춰 연결하며 인증·대화 소유권 검사는 서버에서 수행한다. FAQ는 권한을
변경하거나 실제 계정·보고서·설비 상태를 조회하지 않는다.

### 데이터·활성 규칙

- 파일은 `data/faq/service_v1.toml`, `schema_version=1`이다. `topics`는 ID·제목·
  표시 순서·active, `faqs`는 ID·버전·주제·대표 질문·순서·active·유사 표현·답변·
  검토일·확인 근거를 가진다. 유사 표현은 참고 자료이며 현재 자동 매칭하지 않는다.
- ID는 안정적으로 유지하며 재사용하지 않는다. 질문·답변·근거를 수정하면 해당
  `faq_version`을 올린다. 파일 이름의 v1은 형식 세대이며 각 답변의 버전과 별개다.
- `active` 기본값은 false다. 활성 질문은 빈 답변 없이 검토일·근거가 있어야 하며
  미래 검토일·ID 중복·없는 주제 참조·알 수 없는 필드는 파일 로드 실패다.
- 활성 주제와 활성 질문의 교집합만 제공한다. 비활성/미검토 초안은 직접 ID 조회도
  불가하고 공개 질문이 없는 주제는 숨긴다. 주제·질문은 order 다음 ID 순으로 정렬한다.
- 현재 데이터는 요청에 따라 기존 제안 목록의 제출 필수 내용·제출 후 수정·승인 순서
  3개와 기능/보고서 접근 안내 2개를 활성화했다. 근거는 코드·문서 대조이며 별도
  현업 승인 기록을 의미하지 않는다. 문의 안내 2개는 사용자 지정 근거인 GitHub dev의
  `docs/AUTH.md`를 확인해 활성화했다. 작성·제출은 현장 점검자, 검토·최종 승인은
  보전 팀장·관제 담당자라는 업무 기준이다. 특정 개인·부서·전화번호는 추정하지 않는다.
  열람 문제와 중복되는 `FAQ-CONTACT-001`은 사용자 요청으로 삭제했으며 ID를 재사용하지
  않는다. 현재 활성 FAQ는 총 7개다.
- 사용자 합의에 따라 현장 책임자는 FAQ 안내에서 제외한다. 참고 문서와 기존
  `Role.SITE_MANAGER`에는 아직 남아 있으므로 저장소 전체 역할 제거와 기존 계정·DB
  정리는 별도 변경이 필요하다. FAQ 작업이 기존 권한 모델을 변경하지는 않는다.
- 파일은 로드 시 한 번 읽는 스냅샷이다. 편집 후 `load_faq_catalog()`로 새 인스턴스를
  만들고 API 수명주기에서 교체한다(#91). 운영 파일 변경은 검토·버전 관리 후 배포한다.

### 오류 정책

| 공개 오류 | 의미 | 후속 API 제안 |
|---|---|---|
| `FaqNotFoundError` | 없는/비활성 FAQ, 숨긴/빈 주제. 동일한 안전한 안내 | 404, 목록 새로고침·채팅 시작 안내 |
| `FaqVersionConflictError` | 목록에서 선택한 버전과 현재 답변 버전이 다름 | 409, 목록 재조회 |
| `FaqCatalogError` | 파일 없음·구문/데이터 오류 | 503 또는 서비스 시작 실패, 운영자 확인 |

카탈로그가 비어 있는 정상 상태는 빈 주제 목록이다. 파일 장애를 빈 목록으로 숨기지
않고, 어떤 오류도 LLM 자동 호출로 처리하지 않는다. UI는 FAQ 조회 실패에도 채팅 시작
버튼을 숨기지 않는다. 대화 저장·멱등성·직전 대화 복원은 #90·#91의 책임이다.

검사: `uv run --no-sync pytest tests/contracts/test_faq_contracts.py tests/agent/test_faq.py`.
목록/선택·검토 상태·중복 ID·버전 충돌·파일 오류·복사 격리·외부 서비스 미호출을 검증한다.
별도 사전 분류기·조건 추출 호출은 #87에 포함하지 않는다. 자유 질문은 #89의
Claude 도구 호출 흐름 안에서 처리하고 실제 검색·출처 상태·API 연결은 #88·#91에서 구현한다.

## 자유 질문과 Claude 도구 호출 (루프 구현, 실사용 연결 대기)

`agent.interface.get_chat_service(knowledge, ...)`가 기존 Claude `create()`와
공용 실행기를 재사용한다. 사용자의 질문을 먼저 다른 분류 모델에 보내지 않는다.
Claude가 `search_knowledge`의 문서 종류·검색어·설비·모델·오류 코드·기간을 선택하고,
`submit_answer`로 검증할 답변을 제출한다. 모호하면 확인 질문을 제출할 수 있다.
자유 질문에 FAQ 내용이 포함되면 `browse_faq`·`get_faq_answer` 도구를 사용할 수 있다.
목록 클릭은 기존 FAQ 직접 반환 경로를 사용하므로 이 루프나 LLM을 거치지 않는다.

검색 입력은 `ChatSearchQuery`, 검색 출력은 `ChatSearchHit` 계약을 사용한다.
`ChatKnowledge`는 사용자별 문서 ACL이 없는 공통 검색 의존성이며, 원시 전역
`Retriever`를 받아 자동 연결하는 기본 구현은 제공하지 않는다. #88·#91에서 다음을 구현한다.

- `validate_query`: 실제 설비·모델·기간과 지원 필터를 검증한다. 미지원 조건을 무시해
  검색 범위를 넓히지 않는다. 잘못되거나 모호하면 `InvalidChatQueryError`다.
  사용자 직책·작성자에 따른 열람 제한은 하지 않는다. 오류에는 비밀값을 담지 않는다.
- `search`: 최신 승인 판·필터 등 검색 대상 정책을 적용하고, 관련 근거의
  최소 본문과 페이지/절·가상 여부 등 서버 메타데이터로 만든 출처를 반환한다.
  정확한 기간 목록·집계는 별도 DB 구조화 경로가 필요하며 현재 루프의 유사 검색으로
  전체 건수라고 답하지 않도록 한다. 이 경로 자체는 #88의 남은 작업이다.
- `is_searchable`: 검색 후와 답변 출처 반환 전에 삭제·개정·승인 상태를 확인한다.
  직책별 권한 검사가 아니다. 상태 변경·확인 장애는 SEARCH_UNAVAILABLE로 구분한다.
  원문은 초안·반려까지 읽을 수 있지만 챗봇의 정비 근거는 최신 승인 판만 사용한다.

선택된 설비·모델·기간은 도구 입력에서 생략하면 보존하고 명시 값은 서버가 검증한다.
검색 결과 개수는 화면 상한을 넘지 않으며 한 답변에서 서로 다른 검색 조건을 섞지 않는다.
한국 시간 기준 날짜를 모델에게 전달하되 상대 기간 해석의 정확성은 서버 검색기에서
확인해야 한다. 이전 대화는 API가 소유권·개인정보·길이를 검증한 `ChatContext`만 받는다.

실행은 최대 12턴(기본은 공용 설정), 검색 8회, 누적 근거 20개·본문 32000자로 제한한다.
검색 한 건 본문은 8000자 이하다. 요청의 timeout_s는 큐 대기·도구·모델 호출 전후 남은
시간을 확인하는 예산이다. 외부 구현도 해당 timeout_s를 지켜야 하며 실행 중 스레드를
강제 종료하는 기능은 아니다. 같은 서비스 객체 호출은 직렬화하고 전용 클라이언트를
주입해야 하며 다른 실행기와 하나의 가변 클라이언트를 동시에 공유하지 않는다.

답변의 출처는 이번 실행에서 도구가 반환한 것만 허용하고, 문서/사례/FAQ 종류와
가상 표시도 검증한다. 존재하지 않는 인용은 모델에게 오류로 돌려 수정하게 한다.
제어·정비 작성·결재 도구는 없다. 본문 주장과 근거의 의미적 부합, 관련도 정책,
공급자별 오류 세분화·사용량·실제 API E2E는 #89의 남은 범위다.

가짜 LLM·공통 검색기로 루프·검증을 검사한다.
`uv run --no-sync pytest tests/agent/test_chat_service.py tests/contracts/test_chat_tools.py`
실제 `ChatKnowledge` 구현과 인증된 API 연결 전에는 사용자 대상 서비스가 아니다.
보고서 원문 조회 API는 모든 로그인 사용자가 초안·반려·과거 버전을 열 수 있고
전체 목록은 `GET /reports?scope=all`을 제공한다. 기존 화면의 내 보고서 필터는 유지한다.

## 후속 API 제안 (#90·#91, 미구현)

기존 인증과 동일한 Bearer 토큰을 사용한다. 요청 사용자 ID는 인증 세션에서 얻는다.

| 경로 | 요청·결과 제안 |
|---|---|
| GET /chat/faq/topics | FaqTopic 목록 |
| GET /chat/faq/topics/{id}/questions | FaqQuestion 목록 |
| POST /chat/conversations/{id}/faq-selections | FaqSelection → 검토 답변·ChatResponse 저장 후 반환 |
| POST /chat/conversations | 빈 대화 생성 → ChatConversation |
| GET /chat/conversations | 내 대화 목록 → ChatConversation 목록(페이지 처리 후속 정의) |
| GET /chat/conversations/{id} | 본인 대화·메시지 재조회, 출처 삭제·개정 상태 재확인 |
| POST /chat/conversations/{id}/messages | ChatQuestion → 단일 ChatResponse |
| POST /chat/conversations/{id}/messages/{request_id}/feedback | 본인 응답 피드백. 세부 계약은 #90에서 정의 |

`request_id`는 한 대화 내 중복 전송 식별자다. 동일 ID·동일 질문은 저장 응답을 반환하고,
같은 ID의 다른 본문은 409로 거부하는 방식을 제안한다. 실패 후 재실행 정책과 동시 요청
잠금은 #90에서 정한다. API 입력 검증 422, 미인증 401, 본인 대화 소유권 실패 403,
대화 없음 404, 충돌 409를 제안한다. 서비스 실행 실패는 FAILED와 오류 코드를 사용하고
HTTP 429/502/503/504 매핑은 #91에서 확정한다. 공급자 키 오류를 401로 반환하지 않는다.

## 실행·제한 정책 제안 (#89·#91, 미구현)

공용 LLM은 #101/#107에서 Claude로 전환됐다. `get_llm_client()`와 기존
`LlmClient.create()`를 자유 대화 도구 루프에 재사용하며 별도 공급자 어댑터를 만들지 않는다.
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

② #87 FAQ 목록·선택 조회 → ③ #88 허용 근거 검색 → ④ #89 Claude 자유 대화·응답 검증 →
⑤ #90 저장 → ⑥ #91 API → ⑦ #92 hmi/web → ⑧ #93 통합 평가 순이다.
⑤는 ① 이후 독립 진행할 수 있다. 공용 LLM 전환 #101은 완료됐으며 #89는 기존 Claude
클라이언트를 연결하고 챗봇 응답 검증·사용량 수집·호출 제한을 구현한다.
#74 관련도 정책·#75 평가·#76 청킹은 담당 이슈에서 처리한다.

검증은 `uv run --no-sync pytest tests/contracts tests/agent`와 `make check`다.
실제 상용 API E2E·DB·HMI 실행 검증은 연결 구현 후 각 이슈에서 수행한다.
