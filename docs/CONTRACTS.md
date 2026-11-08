# 데이터 계약 (초안 v0.1)

## 선택적 Unreal 상태 문맥 v1

영향 모듈: contracts, api, detector, frontend, 외부 Unreal 송신기.
`SimulatorOperatingContext`는 기존 `TelemetryRecord` 15개 필드를 변경하지 않는
선택적 계약이다. `UNREAL_STATE`에서만 외피
`{message_type: "telemetry_with_context_v1", telemetry: <기존 15필드>, context: <문맥>}`를 받는다.
기존 CSV·ML 수집·NONE/RUN_ONLY/MINIMAL/SIM_RPM 입력은 그대로 유지한다.

- `version=unreal-state-v1`, `source_id`: 실행별 원천 식별자.
- `run_cmd`, `run_started_at`: 시뮬레이터 RUN 상태와 실제 시작 시각.
- `simulation_seconds`, `run_started_simulation_seconds`,
  `last_infeed_simulation_seconds`, `last_outfeed_simulation_seconds`와 각 이벤트·재고의
  `simulation_seconds`: pause·RUN 해제에 멈추는 누적 Unreal RUN 시계다. 이송·투입·예열 기간과
  P02/P07의 60초 창에만 사용한다. UTC 측정·사건·보고서 시각은 변경하지 않는다.
- `fixed_speed`, `same_load`, `vibration_comparable`: 합성 레시피 비교 조건. 미확인은
  null이며 실제 PLC·물리 하중·승인 진동 기준을 확인했다는 뜻이 아니다.
- `recipe_id`, `config_version`: 합성 설정 식별자. 변경 시 판정 시간창을 끊는다.
- `downstream_ready`: 독립형 시뮬레이터의 명시적 하류 가용 설정.
- `origin_verified_empty`: 실제 트레이 액터 재고와 양쪽 센서를 확인한 빈 상태에서
  시작해 추적을 유지했다는 원천 선언. 센서 false 두 개만으로 추정하지 않는다.
- `events_complete`, `sequence`: 이벤트 누락 여부와 증가하는 원천 순번.
- `events`: 최대 128개, 트레이 ID·UTC 시각·순번·infeed/outfeed. 다중 충돌 컴포넌트를
  트레이 한 개로 중복 제거하며, 표본 사이의 짧은 통과도 이벤트로 전달한다.
- `pending`: 최대 64개, 입구를 통과하고 출구 통과 전인 트레이의 ID·입구 시각·순번.
  새 연결의 체크포인트이며 과거 이송 통계나 기존 미회복 사건의 회복 근거는 아니다.
- `last_infeed_at`, `last_outfeed_at`: 원천 마지막 통과 시각 또는 null.

추가 필드·중복 JSON 키·비정상 순번·미래/시간대 없는 시각은 거부한다.
이벤트 연속성·FIFO·재고 불일치는 D04, 활성 규칙에 필요한 비교 문맥 누락은 D05다.
알려진 기동 유예·예열 대기는 미평가이며 문맥 누락으로 집계하지 않는다.
이 프로필에서 M04와 M19는 필요한 근거가 없어 명시적으로 제외하며,
ACK와 latest/stream의 `rule_coverage.excluded`에 사유를 제공한다.
미평가를 정상으로 표시하거나 승인된 기준을 만들어 넣지 않는다.

코드 위치: `src/weeing_weeing/contracts/`. 이 문서는 요약이고, 필드의 정확한 정의는 코드가 기준이다.

## 원인 후보의 점검 우선순위

영향 모듈: contracts, agent(단일·멀티 분석 및 검증), api·db(기존 JSON 저장/조회),
frontend·hmi/web(분석 결과·단계·보고서 표시). DB 마이그레이션이나 사람 작성·결재 칸 변경은 없다.

- `CauseCandidate.inspection_priority`: 선택적 `우선 확인` / `후속 확인`.
- `CauseCandidate.priority_reason`: 우선순위가 있으면 공백이 아닌 근거 설명이 필수다.
  우선순위 없는 이유만 저장하거나 알 수 없는 우선순위를 저장하면 거부한다.
- `likelihood`: 과거 상/중/하/미평가 값의 역직렬화를 위해 선택적으로 보존한다.
  새 분석 제출 스키마에는 없으며 새 결과에서는 null이다. 등급을 우선순위로 자동 변환하지 않는다.
- 새 모델 제출은 두 새 필드를 필수로 요구하며 관련 출처·센서 수치 검사는 유지한다.
  기존 결과는 필드가 없어도 읽고 화면에는 점검 우선순위 미지정으로 표시한다.
- 우선 확인은 실제 원인 확률이 아니다. 안전상 선행 조건·공식 순서·현재 코드/증상과
  근거의 관련성으로 점검 순서를 제안한다. 현장 점검 전 사용이므로 현재 점검 결과는 필수가 아니다.
  문서·사례가 없으면 기존대로 INSUFFICIENT_EVIDENCE이며 안전·승인 조건을 완화하지 않는다.
- 이전 저장 분석과 완료 체크포인트를 재해석하거나 유료 호출로 자동 갱신하지 않는다.
  새 기준은 새 분석에 적용된다. 프롬프트 버전은 단일 v3, 멀티 v6이다.

## 멀티 사건 분석 단계 결과

`contracts/analysis_workflow.py`를 추가한다. 영향 모듈은 agent·api·db·hmi/web이며,
이전 버전에서 `CauseCandidate.likelihood`에 `미평가`, `Incident`에 선택적
`telemetry_provenance`를 추가했다. 새 점검 우선순위 계약은 위 절을 따른다. 보고서의 사람 작성·결재 계약은 유지한다.

- `Evidence.title/page`: 선택적 문서명과 PDF 실제 페이지(표지 포함, 1부터 시작).
  저장된 청크 메타데이터에서 전달하며 절 제목과 페이지를 함께 보존한다. 청크 순번을 페이지로
  추측하지 않는다. 과거 분석에서 이 필드가 없으면 기존 citation/section으로 표시한다.
  영향 모듈: contracts, rag, api, agent·db(기존 JSON 보존), hmi/web.
  긴 evidence_id는 내부 인용 검증에 유지하며 HMI의 기본 출처 표시는 문서명·버전·PDF 페이지다.

- 과거 `미평가`: 원인 가능성이 낮다는 의미가 아니라 현재 관측으로 등급을 매길 수 없다는 의미다.
  관련 문서에 근거한 점검 후보를 제시할 수 있다. 실제 검색 근거 없는 OK는 계속 거부한다.
- `TelemetryProvenance`: origin(UNKNOWN/SIMULATION/REPLAY/MEASURED), 선택적
  expected_interval_s(0초 초과~60초). 출처·주기는 송신자 선언이며 독립적 실측 검증이 아니다.
  기존 15필드 TelemetryRecord/CSV는 변경하지 않고 연결 정보와 telemetry.provenance JSON에 저장한다.
  과거 행은 null로 남겨 출처 미확인으로 처리한다. 같은 표본 재전송으로 출처를 바꾸지 않는다.
  API가 사건·분석 입력 스냅샷에도 출처를 복사해 센서 도구를 사용하지 않아도 구분한다.

- `ResearchResult`: 인용 ID가 있는 조사 결과와 한계. 실제 확보한 근거만 인용한다.
- `MaintenanceReference`와 `ResearchResult/AnalysisResult.reference_cases`: 참고 정비 사례
  최대 2건. 당시 증상·실제 조치·결과·현재 사건과의 유사점·차이점/적용 한계(각 400자),
  같은 보고서 판본의 근거 ID를 보존한다. 알 수 없는 출처, 여러 보고서를 섞은 사례와 같은
  보고서 중복을 거부한다. 조사에서는 reports 역할만 제출할 수 있다. 멀티 통합 분석의 내부
  제출 필드 reference_case_indices로 조사에서 선별한 사례를 선택하고 서버가 원문 요약을
  그대로 복사한다. 미존재·중복·음수·비정수 위치를 거부한다. 사례 전용 출처도 최종 evidence에
  유지한다. 과거 JSON·단일 분석은 기본 빈 목록이며 기존 DB JSON에 저장하므로 새 마이그레이션은
  없다. 영향 모듈: contracts, agent, api·db(JSON 저장/조회), hmi/web. 보고서의 사람 작성·결재
  필드는 변경하지 않는다.
- `VerificationResult`: PASS/REVISE/INSUFFICIENT_EVIDENCE, 요약과 구체적인 주장·이유·수정 요청.
  PASS에 미해결 지적을 넣거나 구체적인 지적 없이 REVISE를 제출할 수 없다.
- `AnalysisAgentRun`: documents/reports/synthesis/verification 역할과 시도 1~2,
  PENDING/RUNNING/COMPLETED/FAILED/SKIPPED, 원문 근거·조사·분석·검증 결과,
  시각·모델·프롬프트 버전·호출 수·사용량·오류 코드. 없는 근거 ID 인용과 알 수 없는 필드를 거부한다.
  사용량 누락은 null이며 SKIPPED는 검증 통과가 아니다. 내부 대화·thinking 필드는 없다.
  `sensor_windows`에는 조회한 통계·quality(출처별 표본 수, 요청/반환 범위, 미관측 구간,
  선언 전송 주기)를 함께 공개한다. 원시 센서 행은 넣지 않는다.
  `reused_from_job_id`가 있으면 이전 작업의 완료 결과를 재사용한 것이며, 표시되는 통계는
  원래 실행의 통계다. 해당 단계의 새 호출 비용으로 합산하지 않는다.
- `AnalysisCheckpoint`: 버전·사건 ID·검증 설정·역할별 결과·센서 조회 통계 스냅샷.
  완료 단계의 출력 누락, 중복 역할/시도, 분석 사건 ID 불일치를 거부한다.
  서버 내부 재개 입력으로만 사용하며 HTTP 요청으로 받거나 조회 응답에 노출하지 않는다.
- 기존 `GET /incidents/{id}/analysis` 응답에 최신 작업 ID에 연결된 `stages` 목록을 추가한다.
  단일 분석·과거 작업은 빈 목록이다. 기존 job/analysis 필드는 유지한다.
  실패 작업은 `retry_mode=resume`(체크포인트 있음) 또는 `restart`(과거/단일 작업),
  나머지는 null이다. 검증 반려·근거 부족은 완료 판정이므로 재시도 대상이 아니다.
- 기존 `POST /incidents/{id}/analysis/retry`는 현장 점검자·보전 팀장·관제 담당자가 호출한다.
  request_id로 중복 실행을 막고 선택적 job_id로 화면의 작업과 현재 작업을 대조한다.
  새 작업을 예약하면서 완료 단계와 체크포인트를 복사하며 원래 실패 기록을 변경하지 않는다.
  사건에 최종 승인된 보고서가 있으면 새 요청은 409이며 retry_mode는 null이다.
  이미 접수한 request_id의 재전송은 기존 응답만 반환하고 추가 실행하지 않는다.

실행·설정·저장 정책: [MULTI_AGENT_ANALYSIS](MULTI_AGENT_ANALYSIS.md).
역할별 지시 조합·입력·제출 검사: [MULTI_AGENT_PROMPTS](MULTI_AGENT_PROMPTS.md).

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
| `DocumentRecord` | 문서 레지스트리 설계(#59·#60), 웹 업로드·삭제 API |
| `UserAccount` | 노션 '전체 할 일 정리 > 8. 사용자·권한', `Role`(직책 4종, 10/16 회의) |

원본 문서는 `data/manuals/`, `data/rulebase/`, `data/regulations/`, `data/templates/`에 있다.

`ReportDocument.index_status`는 최종 승인 판의 검색 등록 상태다. `pending`(대기),
`indexed`(벡터 저장 완료), `failed`(실패·수동 재시도 대상), 승인 전 `None`을 사용한다.
영향 모듈: db의 승인 outbox, api의 응답·백그라운드 처리, hmi/web의 상태 표시.

## 핵심 규칙

- **센서 기본 조회·후보별 설명·조치 출처**: 새 멀티 분석은 센서 조회기가 주입되면 통합 분석
  직전에 기본 조회를 한 번 수행한다. sensor_windows의 purpose=baseline으로 완료(0건 포함)를
  구분하고 체크포인트에서 재사용한다. 후보별 basis는 문서와 후보의 연결 설명으로 보존하고,
  observations는 제출된 센서 수치를 검증한 뒤 서버가 작성한다. unconfirmed는 후보별
  미확인 사항이다. 새 멀티 제출의 sensor_claim_indices는 검증 수치 목록 위치를 가리키며
  저장 결과에는 남기지 않는다. 과거/단일 분석에는 기존 필드와 빈 목록 기본값을 허용한다.
  action_citations와 approval_citations는 각각 권고 조치·승인 필요 조치의 위치(action_index,
  0부터)와 evidence_ids다. 새 멀티 제출은 모든 항목의 출처를 요구하며,
  저장 계약도 없는 위치·출처와 중복 위치를 거부한다. 영향 모듈: contracts, agent,
  api(기존 센서 조회 주입), db(JSON·체크포인트 저장), hmi/web. 테이블 변경은 없다.

- **분석 검증과 점검 출처**: `AnalysisResult.status`에 `VERIFICATION_FAILED`를 추가한다.
  두 번째 검증에서도 수정이 필요한 경우의 검증 미통과 초안이며, 근거 부족 및 시스템 실패와
  구분한다. 초안은 조회용으로 유지하고 보고서의 확정 가능한 AI 초안에는 사용하지 않는다.
  `check_citations`는 점검 위치(check_index, 0부터)와 evidence_ids의 목록이다.
  과거/단일 분석은 빈 목록을 허용하고 새 멀티 분석 제출은 모든 점검에 출처를 요구한다.
  문장에 근거 ID를 중복 출력할 필요는 없다. 없는 출처·점검 및 중복 위치를 거부한다.
  `Evidence.report_timing`은 서버가 보고서 조치와 현재 사건 최초 감지의 차이를 계산한
  메타데이터다. 조치 순번·시간대 포함 시각·offset_seconds(조치-사건)를 제공하며,
  음수는 사건 이전이다. 원문은 변경하지 않는다.
  영향 모듈: contracts, agent, api, db(JSON 저장), hmi/web. 테이블 변경은 없다.

- **사건번호**: `Incident.incident_number`는 DB 저장 시 발급하는 선택 필드다.
  내부 연결용 `incident_id`는 유지하며, 첫 에러코드·한국 시간 최초 감지일·순번으로
  `INC-BTT2-M10-20261105-001` 형식을 만든다. 순번은 삭제 후에도 재사용하지 않는다.
  DB 저장 전과 마이그레이션 전 기존 사건에는 번호가 없을 수 있다. 영향 모듈: contracts,
  db, api, hmi/web. 분석 작업과 보고서 연결에는 기존 incident_id를 쓴다.

- **Telemetry**: 15컬럼 순서 고정(`COLUMNS`). 전류·온도 빈 값은 0이 아니라 `None`. `timestamp`는 시간대 필수
- **Incident**: 같은 현상이 이어지면 새로 만들지 않고 갱신. 묶인 원시 코드를 `codes`에 전부 보존. 회복(`RECOVERED`)과 종결(`CLOSED`)은 다르다
- **AnalysisResult**: `status=OK`이면 근거(`evidence`)가 1개 이상 있어야 하고, 원인 후보마다 근거를 1개 이상 인용해야 하며, 인용한 `evidence_ids`는 실제 근거 목록에 있어야 한다. 검증기가 이를 강제한다
- **Evidence 관련도(#74)**: `score`는 기존 검색 점수(RRF)를 유지하고, 선택 필드 `relevance`로 유한한 리랭커 모델 점수를 전달한다. 미측정은 `None`이며 측정된 0점과 구분한다. 이전 JSON에는 이 필드가 없어도 된다. 관련도는 확률이 아니고 모델별 값의 범위가 달라 음수도 허용한다. 기준값은 #75 평가로 결정한다. 영향 모듈: rag(생성·필터), agent(근거 판단), api·db·HMI(AnalysisResult·보고서 JSON 전달·저장·표시). 새 필드는 기본값 None이며 DB 스키마 변경은 없다.
- **DocumentRecord**: 색인 대상 문서 한 줄(db `document` 테이블 ↔ rag 색인 목록 ↔ api 업로드 상태). `origin`은 seed(카탈로그)·upload·report. 색인 목록은 `status=completed` 행이고 같은 doc_id의 completed는 하나뿐이다. `origin=upload`면 `upload_id` 필수. 삭제 진행·실패 상태는 `deleting`·`delete_failed`이며 색인 대상에서 제외한다. 성공하면 문서의 모든 판을 DB에서 실제 삭제한다. `seed`는 이전에 등록된 문서 호환용이며 새 자동 등록은 없다. `doc_id`·`doc_version`에는 `:`와 공백을 쓸 수 없다(청크 ID 구분자)
- **UserAccount**: 사용자 한 명(사번 `employee_no`, 이름, 직책 `role`, `is_admin`, `is_active`). 비밀번호·세션 토큰은 계약에 없고 db 내부에만 있다. 직책은 업무 권한, `is_admin`은 계정 관리 권한으로 따로 준다. 사번은 보고서의 `ActionTaken.by`·`ApprovalStep.user`와 같은 값을 쓴다
- **MaintenanceReport**: 칸마다 쓰는 주체가 정해져 있다. AI는 `maintenance`·`approval`을 쓰지 않는다. RAG에는 승인된 보고서의 사람 작성 칸만 넣는다
- **보고서 작업 계약(#62)**: 초안은 사건·입력이 덜 채워져도 저장한다. 제출에는 저장된 Incident·필수 사람 입력이 필요하다. 실제 조치는 action_at을 요구하고, 미수행은 actions_taken을 만들지 않는다. 작성자·결재 사번은 인증 계정에서 정하고 expected_revision으로 동시 수정을 검사한다. 과거 버전의 폼·사건/AI 스냅샷은 고정하고 승인 시 #29용 대기 기록을 만든다. 영향 모듈: db, api, HMI. 기존 MaintenanceReport/Agent 계약 유지. [REPORTS](REPORTS.md) 참고.

## 챗봇 1단계 계약 (#86)

코드: `contracts/chat.py`. 영향 모듈: agent(응답 생성),
rag(검색 근거 변환), db(대화 저장), api(인증·조립), hmi/web(상태·출처 표시).
챗봇 계약 자체는 기존 `Incident`, `Evidence`, `AnalysisResult`, `MaintenanceReport`를
변경하지 않는다. #74의 선택 필드 `Evidence.relevance` 확장은 위 공통 규칙을 따른다.

| 계약 | 역할·검증 |
|---|---|
| `ChatQuestion` | UUID 요청 ID, 공백 제거 후 1~2000자 질문, 검색 조건. 사용자·권한·의도 필드 주입 금지 |
| `ChatSearchConditions` | 선택적 설비 ID·모델(1~100자), 시작/종료일, 검색 결과 1~20개(기본 5). 역전 기간·빈 식별자·정수가 아닌 limit 거부 |
| `ChatConversation`, `ChatContext`, `ChatTurn` | 대화 목록 메타데이터(FAQ/CHAT 모드 포함)와 서버가 준비한 최근 문맥. 시간대 필수·갱신 시각 순서 검증. 문맥은 user/assistant만, 최대 20개·각 4000자·총 16000자 |
| `ChatDocumentSource` | 문서 ID·버전·페이지(1 이상) 또는 절 |
| `ChatReportSource` | 보고서 ID·판(1 이상), 가상 여부 `synthetic` 필수. 승인·권한 검증 자체를 대체하지 않음 |
| `ChatHistorySource` | DB 구조화 조회 조건·오류 코드·전체 승인 보고서 수·가상 보고서 수·스냅샷 해시. 0건도 출처로 표시하며 MAINTENANCE_HISTORY 본문에서만 인용 |
| `ChatFaqSource` | FAQ ID·제목·출처 ID(수동 버전 없음) |
| `ChatAnswerPart` | 매뉴얼 기준/과거 정비 사례/FAQ 본문과 출처 ID 목록. 서로 다른 종류의 근거 혼용 거부 |
| `ChatResponse` | 요청 ID·의도·상태·적용 검색 조건·안내·본문·출처·추가 질문·오류·생성 시각 |

의도는 `MANUAL`, `MAINTENANCE_HISTORY`, `INCIDENT`, `FAQ`, `COMBINED`, `OUT_OF_SCOPE`다.
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
기존 `ChatQuestion`·`ChatResponse`와 LLM 경계는 유지한다.
FAQ의 수동 버전·검토일·참고 문서 필드를 제거하며 `ChatFaqSource`에서도 수동 버전을 제거한다.

| 계약 | 역할·검증 |
|---|---|
| `FaqTopic` | 주제 ID·이름·표시 순서. 순서는 0 이상 정수이며 ID는 영문/숫자로 시작하는 영문·숫자·`_`·`-` 1~64자 |
| `FaqQuestion` | FAQ ID·주제 ID·대표 질문·순서. 질문은 공백 제거 후 1~2000자 |
| `FaqSelection` | 요청 UUID·FAQ ID만 허용. 사용자 ID·답변 본문을 클라이언트가 지정할 수 없음 |
| `FaqAnswer` | 서버의 대표 질문·답변(1~4000자)·`ChatFaqSource`. 질문과 출처의 FAQ ID 일치 필수 |

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
최종 답변 상태·인용은 `ChatResponse` 검증도 적용한다. `ChatSource` 판별 union에
`HISTORY_QUERY`가 추가되므로 API·저장·화면의 출처 역직렬화는 이 종류도 지원해야 한다.
`ChatSearchHit`의 문서/보고서 종류는 그대로 유지한다.

- `ChatHistoryQuery`: 설비·실제 조치일 조건·정의된 오류 코드. 유사 질의문·사용자 권한을 받지 않는다.
- `ChatHistoryResult`: `ChatHistorySource`, 제한된 보고서 목록, `truncated`. total은 top-k가 아닌
  조건에 맞는 **최신 승인 보고서 수**다. 같은 사건에 여러 보고서가 있을 수 있어 전체 고장 발생
  횟수와 다르다. 가상 사례 수는 synthetic_total로 따로 제공한다.
- 목록 길이는 min(total, limit), truncated는 total > 목록 길이와 일치해야 한다.
  0건은 reports=[], truncated=false이며 DB 조회 출처를 인용할 수 있다.
- 조회 스냅샷은 답변 직전 DB에서 다시 계산한다. 자료 추가·개정·삭제로 바뀌면 출처 상태
  변경으로 실패한다. 자동 재시도나 이전 집계 재사용은 하지 않는다.

`api/chat_knowledge.py`가 DB·공유 RAG를 조립한다. 자세한 지원 조건·실행 방법은
[CHATBOT](CHATBOT.md)을 따른다.

## 개인 대화 저장 계약 (#90)

`contracts/chat_storage.py`는 대화 저장·본인 접근·중복 실행 방지에 필요한 계약만 둔다.
영향 모듈은 db(저장·소유권·예약), api(인증 후 실행 조립), 향후 hmi/web(상태·기록 표시)다.
기존 `ChatQuestion`·`ChatResponse` 구조는 유지하며 `ChatConversation`에 기본 FAQ인
FAQ/CHAT 모드를 추가한다. 별도 ChatSavedConversation 파생 모델은 두지 않는다.

- `ChatSubmission`: request_id + CHAT(질문과 선택적 모델) 또는 FAQ(ID). 모델은 재시도와 중복 요청 비교에 포함한다. 사용자/소유자 ID,
  이전 문맥·의도·실행 토큰은 입력 불가. 생략한 conditions는 첫 예약의 대화 조건을 사용한다.
- `ChatRequestView`: 상태, 최초 예약 조건, 저장 응답, 재시도 가능 여부와 안전한 오류 코드.
  없는/비활성 FAQ는 FAQ_NOT_FOUND다. 같은 ID 재실행 없이 목록 새로고침 후 새 ID로 선택한다.
  RESERVED(실행 전), RUNNING(실행 시작), COMPLETED(응답 저장), FAILED(실행 전 실패),
  UNKNOWN(실행 이후 결과 불명)을 구분한다. COMPLETED는 실패 응답도 보존한다.
- 같은 대화의 동일 request_id·동일 본문은 현재 상태/저장 응답을 반환한다. 다른 본문은 충돌.
  실행 전 실패만 `retry=True`를 명시해 재예약할 수 있다. 장애 회복 가능성을 나타내는
  `ChatResponse.failure.retryable`과 같은 ID 재실행 허가인 `ChatRequestView.retry_allowed`를 구분한다.
- `ChatSavedMessage`: 저장된 질문/답변의 순번·시각·요청 연결과 원본 응답.
  모델 문맥용 ChatTurn의 길이 제한과 달리 전체 과거 답변을 보존한다.
- `ChatConversationPage`: 대화 정보·제한된 메시지 목록·다음 페이지 유무. 긴 기록을 한꺼번에 읽지 않는다.

사용량 저장 모델·출처 현재 상태 모델·피드백 모델은 두지 않는다. 에이전트의 기존
사용량 수집과 새 답변의 검색·출처 검증은 유지한다. 과거 기록은 당시 스냅샷 그대로 반환한다.
목록·조회·문맥·재전송·수정·삭제·결과 저장 모두 활성 사용자와 소유자를 검사하며 관리자도
예외 없다. 타인 대화와 없는 대화는 동일 ChatNotFoundError(HTTP 404)다.
이전 DB JSON의 폐지된 FAQ 버전은 읽기 시 제외하며 기존 질문·답변과 중복 ID는 유지한다.
새 요청은 폐지한 필드를 허용하지 않는다. DB 스키마 변경·데이터 삭제는 없다.
보관·예약 만료·동시성·기존 DB 호환은 [CHAT_STORAGE](CHAT_STORAGE.md),
HTTP 경로·상태·응답 매핑은 [CHAT_API](CHAT_API.md)를 따른다.
POST /messages는 기존 ChatQuestion, /faq-selections는 FaqSelection을 받고
서버가 ChatSubmission으로 변환한다. 새 HTTP 입력 모델인 ConversationCreate/Update는
api 내부에만 두며 contracts의 종류를 늘리지 않는다. 영향 모듈은 db·api·향후 화면이다.

## 아직 정하지 않은 것

- 코드별 담당 레이어(PLC가 판정할 코드 vs Main Engine이 판정할 코드)
- `PlcState` 상태 이름과 전환 규칙 (`plc/interface.py`, 3차 착수 때)
- 결재선에서 현장 책임자의 역할 (결재 단계인지, 확인 서명만 하는지)
- 보고서 사진 파일 저장 위치

## 바꿀 때

1. `contracts/` 코드와 이 문서를 같은 PR에서 고친다
2. PR 본문의 '변경 사항'에 영향받는 모듈과 담당자를 적는다
3. `tests/contracts/`의 테스트를 함께 고친다


## 현재 알림·회복 사건 조회

영향 모듈: contracts, db(사건 집계), api(조회 조립), agent(도구·근거 검토),
frontend(알림 집계·출처), scripts(터미널 표시). 기존 Incident·보고서 계약과 DB 스키마는 유지한다.

- `ChatIncidentQuery`: ACTIVE/RECOVERED, 선택적 설비·이상 코드·등급·사건 ID,
  시간대 포함 시작/종료 시각, 목록 상한 1~20. 코드·역전 기간·시간대 누락을 거부한다.
- `ChatIncidentSource`: `kind=INCIDENT_QUERY`, 적용 조회 조건·전체 건수·Warning/Error별 건수,
  조회 시각·선택된 사건 ID. `ChatAnswerPart.kind=INCIDENT`에서 인용하며, 다른 자료와 결합하면 COMBINED다.
- `ChatIncidentItem`/`ChatIncidentResult`: 발생·마지막 감지·회복 시각과 기존 SensorEvidence의
  측정값·단위·판정 기준·관측 설명을 전달한다. 사번·결재·PLC 문맥은 포함하지 않는다.
  전체 건수와 제한된 목록을 구분하고 0건도 유효한 조회 근거로 취급한다.
- ACTIVE는 OPEN/ACKNOWLEDGED이면서 Warning/Error인 사건이다.
  RECOVERED는 회복 시각이 있는 RECOVERED/CLOSED 사건이며, 회복 시각 내림차순이다.
  시간 범위와 사건 ID가 없으면 조건에 맞는 최신 회복 한 건을 서버가 선택한다.
  명시한 시간 범위에 결과가 없을 때 다른 시점의 사건으로 대체하지 않는다.
- 시간 조건은 ACTIVE의 최초 발생 시각, RECOVERED의 회복 시각 기준이며 양 끝을 포함한다.
  화면에서 선택한 날짜는 한국 시간의 하루 전체로 변환하고 설비 선택도 보존한다.
  모델 필터는 사건에 정보가 없으므로 조용히 무시하지 않고 미지원으로 안내한다.
- 사건 근거는 조회 시점 스냅샷이다. 지속/회복 갱신 때문에 생성 도중 답변을 실패시키지 않으며,
  인용 사건의 삭제 여부는 반환 전에 재확인한다. 조회 시각을 센서 관측 시각으로 설명하지 않는다.

## 검증 후 채팅 SSE·마크다운

`contracts/chat_stream.py`의 전송 계약이며 기존 ChatResponse·대화 저장 스키마는 유지한다.
영향 모듈: contracts, agent(선택적 ProgressChatService), api(SSE·저장), frontend(수신·마크다운).

- `ChatStreamProgress`: event=progress, request_id, phase(accepted/generating/searching/verifying/saving).
  실제 실행 단계만 전송하며 질문·도구 인자·모델 초안은 담지 않는다.
- `ChatStreamDelta`: event=delta, request_id, text(1~2048자). 공백과 줄바꿈을 보존한다.
  응답이 검증되고 DB 저장까지 완료된 OK 답변에만 전송한다.
- `ChatStreamDone`: event=done, request(기존 ChatRequestView). 최종 상태·본문·출처의 기준이다.
- `ChatStreamError`: event=error, 안전한 message와 status_code. 전송 시작 뒤 오류에 사용한다.
  request_reserved=False인 경우만 예약 전 거절로 판단한다. 나머지는 접수됐을 가능성이 있어 새로운 ID로 자동 재실행하지 않는다.

본문 `parts.text`는 각 부분이 독립적인 마크다운이다. 프론트엔드는 제목·목록·강조·표·코드를
렌더링하며 한 번 개행도 실제 줄바꿈으로 보존한다. 원시 HTML·외부 이미지·모델 생성 링크는
실행/로드하지 않고 기존 출처 버튼을 사용한다.
