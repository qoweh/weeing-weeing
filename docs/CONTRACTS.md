# 데이터 계약 (초안 v0.1)

코드 위치: `src/weeing_weeing/contracts/`. 이 문서는 요약이고, 필드의 정확한 정의는 코드가 기준이다.

> **상태: 초안.** 노션 자료를 옮겨 만든 첫 버전이다. 각 담당자가 1차 개발을 하면서 필요한 필드를 PR로 고친다.

## 근거 자료

| 계약 | 근거 |
|---|---|
| `TelemetryRecord` | 룰베이스 최종 정의서 v2.0 2절, 노션 길용현 데이터 규격 표 |
| `Severity`, `CODES` | 룰베이스 최종 정의서 v2.0 3·4·5·7·8·9절 (코드 31개, `BTT2-` 접두사) |
| `Incident` | 정의서 v2.0 10절 '사건 저장 계약', 노션 김민우 정리본 예시 JSON |
| `Evidence`, `AnalysisResult` | 1차 분담 'AI Agent 4. 결과 구조화 및 검증', 김민우 정리본 `ai_analysis` |
| `MaintenanceReport` | 김민우 정리본 4장 보고서 규격 v1.0 초안, 보고서 양식 v1.2 |
| `ReportDraft`, `ReportFormData`, `ReportDocument`, `ReportSummary` | #62 임시 저장·조회·결재. 미완성 초안과 제출 계약 구분 |
| `DocumentRecord` | 문서 레지스트리 설계(#59·#60), `data/catalog.toml` 항목, 업로드 API 응답 |
| `UserAccount` | 노션 '전체 할 일 정리 > 8. 사용자·권한', `Role`(직책 4종, 10/16 회의) |

원본 문서는 `data/manuals/`, `data/rulebase/`, `data/regulations/`, `data/templates/`에 있다.

`ReportDocument.index_status`는 최종 승인 판의 검색 등록 상태다. `pending`(대기),
`indexed`(벡터 저장 완료), `failed`(실패·수동 재시도 대상), 승인 전 `None`을 사용한다.
영향 모듈: db의 승인 outbox, api의 응답·백그라운드 처리, hmi/web의 상태 표시.

## 핵심 규칙

- **Telemetry**: 15컬럼 순서 고정(`COLUMNS`). 전류·온도 빈 값은 0이 아니라 `None`. `timestamp`는 시간대 필수
- **Incident**: 같은 현상이 이어지면 새로 만들지 않고 갱신. 묶인 원시 코드를 `codes`에 전부 보존. 회복(`RECOVERED`)과 종결(`CLOSED`)은 다르다
- **AnalysisResult**: `status=OK`이면 근거(`evidence`)가 1개 이상 있어야 하고, 원인 후보마다 근거를 1개 이상 인용해야 하며, 인용한 `evidence_ids`는 실제 근거 목록에 있어야 한다. 검증기가 이를 강제한다
- **DocumentRecord**: 색인 대상 문서 한 줄(db `document` 테이블 ↔ rag 색인 목록 ↔ api 업로드 상태). `origin`은 seed(카탈로그)·upload·report. 색인 목록은 `status=completed` 행이고 같은 doc_id의 completed는 하나뿐이다. `origin=upload`면 `upload_id` 필수. `doc_id`·`doc_version`에는 `:`와 공백을 쓸 수 없다(청크 ID 구분자)
- **UserAccount**: 사용자 한 명(사번 `employee_no`, 이름, 직책 `role`, `is_admin`, `is_active`). 비밀번호·세션 토큰은 계약에 없고 db 내부에만 있다. 직책은 업무 권한, `is_admin`은 계정 관리 권한으로 따로 준다. 사번은 보고서의 `ActionTaken.by`·`ApprovalStep.user`와 같은 값을 쓴다
- **MaintenanceReport**: 칸마다 쓰는 주체가 정해져 있다. AI는 `maintenance`·`approval`을 쓰지 않는다. RAG에는 승인된 보고서의 사람 작성 칸만 넣는다
- **보고서 작업 계약(#62)**: 초안은 사건·입력이 덜 채워져도 저장한다. 제출에는 저장된 Incident·필수 사람 입력이 필요하다. 실제 조치는 action_at을 요구하고, 미수행은 actions_taken을 만들지 않는다. 작성자·결재 사번은 인증 계정에서 정하고 expected_revision으로 동시 수정을 검사한다. 과거 버전의 폼·사건/AI 스냅샷은 고정하고 승인 시 #29용 대기 기록을 만든다. 영향 모듈: db, api, HMI. 기존 MaintenanceReport/Agent 계약 유지. [REPORTS](REPORTS.md) 참고.

## 챗봇 1단계 계약 (#86)

코드: `contracts/chat.py`. 영향 모듈: agent(응답 생성),
rag(검색 근거 변환), db(대화 저장), api(인증·조립), hmi/web(상태·출처 표시).
기존 `Incident`, `Evidence`, `AnalysisResult`, `MaintenanceReport`는 변경하지 않는다.

| 계약 | 역할·검증 |
|---|---|
| `ChatQuestion` | UUID 요청 ID, 공백 제거 후 1~2000자 질문, 검색 조건. 사용자·권한·의도 필드 주입 금지 |
| `ChatSearchConditions` | 선택적 설비 ID·모델(1~100자), 시작/종료일, 검색 결과 1~20개(기본 5). 역전 기간·빈 식별자·정수가 아닌 limit 거부 |
| `ChatConversation`, `ChatContext`, `ChatTurn` | 대화 목록 메타데이터와 서버가 준비한 최근 문맥. 시간대 필수·갱신 시각 순서 검증. 문맥은 user/assistant만, 최대 20개·각 4000자·총 16000자 |
| `ChatDocumentSource` | 문서 ID·버전·페이지(1 이상) 또는 절 |
| `ChatReportSource` | 보고서 ID·판(1 이상), 가상 여부 `synthetic` 필수. 승인·권한 검증 자체를 대체하지 않음 |
| `ChatFaqSource` | 검토된 FAQ ID·버전 |
| `ChatAnswerPart` | 매뉴얼 기준/과거 정비 사례/FAQ 본문과 출처 ID 목록. 서로 다른 종류의 근거 혼용 거부 |
| `ChatResponse` | 요청 ID·의도·상태·적용 검색 조건·안내·본문·출처·추가 질문·오류·생성 시각 |

의도는 `MANUAL`, `MAINTENANCE_HISTORY`, `FAQ`, `COMBINED`, `OUT_OF_SCOPE`다.
모든 챗봇 모델은 알 수 없는 필드를 거부한다. 검색 기간은 실제 조치일의 양 끝 날짜를
포함하며, 한쪽만 지정하면 열린 구간이다. 기간 길이 제한은 아직 강제하지 않는다.
결과 개수는 유사 검색 상한이며 정확한 집계의 전체 건수로 해석하지 않는다.

| 응답 상태 | 의미·기존 분석 정책과 관계 |
|---|---|
| `OK` | 답변 본문·출처 필수. 출처 ID 중복·없는 출처 인용 금지. AnalysisResult의 근거 필수 정책을 따름 |
| `NEEDS_CLARIFICATION` | 확인 질문 1~5개 필수. 검색·분석의 근거 부족과 구별 |
| `INSUFFICIENT_EVIDENCE` | 허용 범위 안에서 쓸 수 있는 근거가 없음. 기존 동일 상태와 같은 정책 |
| `OUT_OF_SCOPE` | 기능 범위 밖. 의도도 OUT_OF_SCOPE여야 함 |
| `FAILED` | 시스템 처리 실패. `ChatFailure`(오류 코드·재시도 가능 여부) 필수. 기존 FAILED와 같은 정책 |

OK 이외에는 답변 본문·출처를 반환하지 않는다. 오류는 FAILED에만, 확인 질문은
NEEDS_CLARIFICATION에만 허용한다. 공급자 인증 오류는 `LLM_AUTHENTICATION`으로
전달하며 사용자 로그인 오류와 구별한다. `message`는 상태 안내용이고 근거 기반 답변은
반드시 `parts`에 둔다. 실제로 검색된 허용 근거인지, 본문 주장과 부합하는지,
가상 사례 표시·최신 승인 판·문서 삭제/개정 상태는 #88·#89·#91에서 추가 검증한다.
문서 원문은 로그인 사용자에게 직책과 무관하게 공개하며 보고서 초안·반려 판도 포함한다.
임의 원문 URL은 계약으로 받지 않으며 서버가 출처 식별자로 허용된 내부 경로를 만든다.

LLM 공통 경계는 #101/#107에서 구현된 `LlmClient`를 그대로 사용한다.
`get_llm_client()`는 `ClaudeClient`를 생성하고 `generate_json()`은 JSON 문자열,
`create()`는 도구 호출 응답을 반환한다. 공급자·모델은 `provider`·`model_name`,
직전 호출 사용량은 `last_usage`의 `input_tokens`·`output_tokens`·`total_s`로 제공된다.
이번 단계의 챗봇 응답에는 사용량 필드를 두지 않는다. 실제 호출 연결 시 기존
`LlmUsage`의 재사용·변환과 저장 방식을 #89·#90에서 결정한다. 공유 `last_usage`의
동시 호출 경합 방지와 SDK 재시도·실패 사용량 추적도 그때 구현한다.

기존 공용 오류도 유지한다. `LlmTimeoutError`는 시간 초과,
`LlmUnavailableError`는 연결 또는 공급자 인증 실패,
`LlmModelMissingError`는 모델 사용 불가, `LlmRefusedError`는 모델 거부다.
모두 `LlmError` 하위 타입이다. 429·5xx는 현재 일반 `LlmError`이므로 챗봇 오류 코드의
세밀한 매핑은 #89에서 공용 구현과 함께 보완한다. 문자열 메시지로 인증/연결 실패를
추측해 분류하지 않는다. 공급자 오류를 사용자 로그인 401로 반환하지 않는다.
예외 메시지에는 키·공급자 원문 본문을 담지 않는다.

상용 API 어댑터·설정 전환은 #101/#107에서 완료됐다. #89는 기존 공용 클라이언트를
챗봇에 연결하고 응답 검증·제한·오류 매핑을 보완한다. 이번 챗봇 계약 작업은
공용 클라이언트·팩토리·설정·의존성을 다시 구현하지 않는다.
API 경로·실행 정책 제안과 후속 범위는 [CHATBOT](CHATBOT.md)을 참고한다.

## FAQ 선택 조회 계약 (#87)

`contracts/faq.py`를 추가한다. 영향 모듈은 agent(파일 조회·응답 변환), api(목록·선택
요청 연결), db(선택 메시지 스냅샷 저장), hmi/web(주제·질문 버튼)이다.
기존 `ChatQuestion`·`ChatResponse`·`ChatFaqSource`와 LLM 계약은 유지한다.

| 계약 | 역할·검증 |
|---|---|
| `FaqTopic` | 주제 ID·이름·표시 순서. 순서는 0 이상 정수이며 ID는 영문/숫자로 시작하는 영문·숫자·`_`·`-` 1~64자 |
| `FaqQuestion` | FAQ ID·버전·주제 ID·대표 질문·순서. 질문은 공백 제거 후 1~2000자, 버전은 1~64자 |
| `FaqSelection` | 요청 UUID·FAQ ID·버전만 허용. 사용자 ID·답변 본문을 클라이언트가 지정할 수 없음 |
| `FaqAnswer` | 서버의 대표 질문·검토 답변(1~4000자)·검토일·`ChatFaqSource`. 질문과 출처 ID·버전 일치 필수 |

주제·질문·답변의 최상위 필드는 변경할 수 없게 한다. 목록은 새 리스트, 답변은 깊은
복사로 반환하여 호출자의 수정이 카탈로그에 영향을 주지 않게 한다.
선택 조회는 `agent.interface.FaqCatalog`가 담당하며, 파일 단위 검증·활성 정책과
후속 HTTP 매핑은 [CHATBOT](CHATBOT.md)의 FAQ 절을 따른다.

## 자유 대화 검색 도구 계약 (#88·#89·#91)

코드는 `contracts/chat_tools.py`, 공개 경계는 `agent.interface.ChatKnowledge`다.
영향 모듈은 agent(도구 선택·인용 검증), rag·db(조건·검색 대상 정책을 적용한 검색 구현),
api(공통 검색 주입·인증·대화 소유권)다. 기존 `ChatQuestion`·`ChatResponse`는 유지한다.

- `ChatSearchQuery`: 검색 문장 1~2000자, MANUAL/MAINTENANCE_HISTORY,
  기존 `ChatSearchConditions`, 선택적 정의된 오류 코드. 사용자 ID·권한·허용 ID 주입 금지.
- `ChatSearchHit`: 서버가 검증한 문서/보고서 출처와 1~8000자 본문. 문서 위치·판·
  가상 여부를 모델이 만들지 않는다. 실제 실재·필터·최신 승인 검증은 서버 검색기 책임이다.

별도 분류/조건 추출 API 호출 없이 도구 입력에서 조건을 추출하고 서버에서 검증한다.
검색 결과를 모델에 전달하기 전·출처를 노출하기 전 `is_searchable()`로 삭제·개정·승인
상태를 재확인한다. 직책별 문서 ACL은 없다. 검색 오류·출처 상태 변경은 FAILED이며
근거 부족과 구분한다. 대화 소유권·쓰기 권한은 유지한다. 미지원 조건은 재질문 가능한
도구 오류다. 공개 `InvalidChatQueryError`는 안전한 오류 설명만 담는다.
최종 답변 상태·인용은 기존 `ChatResponse` 검증도 적용한다. 실제 검색 연결 전의
모의 테스트용 조립 인터페이스이며 상세 제한·남은 작업은 [CHATBOT](CHATBOT.md)을 따른다.

## 아직 정하지 않은 것

- 코드별 담당 레이어(PLC가 판정할 코드 vs Main Engine이 판정할 코드)
- `PlcState` 상태 이름과 전환 규칙 (`plc/interface.py`, 3차 착수 때)
- 결재선에서 현장 책임자의 역할 (결재 단계인지, 확인 서명만 하는지)
- 보고서 사진 파일 저장 위치

## 바꿀 때

1. `contracts/` 코드와 이 문서를 같은 PR에서 고친다
2. PR 본문의 '변경 사항'에 영향받는 모듈과 담당자를 적는다
3. `tests/contracts/`의 테스트를 함께 고친다
