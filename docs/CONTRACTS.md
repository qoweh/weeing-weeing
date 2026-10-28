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

## 아직 정하지 않은 것

- 코드별 담당 레이어(PLC가 판정할 코드 vs Main Engine이 판정할 코드)
- `PlcState` 상태 이름과 전환 규칙 (`plc/interface.py`, 3차 착수 때)
- 결재선에서 현장 책임자의 역할 (결재 단계인지, 확인 서명만 하는지)
- 보고서 사진 파일 저장 위치

## 바꿀 때

1. `contracts/` 코드와 이 문서를 같은 PR에서 고친다
2. PR 본문의 '변경 사항'에 영향받는 모듈과 담당자를 적는다
3. `tests/contracts/`의 테스트를 함께 고친다
