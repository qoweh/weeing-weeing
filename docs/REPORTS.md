# 보고서 저장·결재 (#62)

`hmi/web/`의 **보고서·결재** 탭에서 사번으로 로그인한다. 기존 회원 API를 사용하며
`frontend/`는 수정하지 않는다. 계정 관리자(is_admin)와 결재 직책은 별개다.

## 준비

프로젝트 루트에서 환경·DB를 준비한다.

```bash
uv sync --locked --no-install-project
make db-up
make db-migrate
make seed-users ARGS=--ask-password
make api
```

웹은 다른 터미널에서 실행한다.

```bash
cd hmi/web
npm ci
npm run dev
```

시연 계정은 I4001(현장 점검자), L2001(보전 팀장), C1001(관제 담당자)이다.
이미 있는 계정은 시드가 변경하지 않는다. 비밀번호는 Git·채팅에 남기지 않는다.
브라우저는 토큰만 현재 탭의 sessionStorage에 보관하고, 로그아웃 시 서버 세션과
브라우저 토큰을 제거한다.

## 흐름

1. 현장 점검자 또는 보전 팀장이 새 보고서를 작성하고 임시 저장한다.
2. 정비 이력의 내 보고서 탭에서 저장한 보고서를 다시 열 수 있다. 결재 대기 탭은 본인이 처리할 보고서를, 내 결재 이력 탭은 보고서별 본인의 최근 처리와 현재 상태를, 정비 이력 탭은 모든 최종 승인 보고서를 보여 준다.
3. 저장된 사건을 선택해 초안을 저장하고 필수 항목을 입력한 후 제출한다.
4. 현장 점검자의 보고서는 보전 팀장이 검토 승인 또는 반려한다.
5. 보전 팀장이 작성한 보고서는 중간 검토 없이 관제 담당자에게 전달된다.
6. 관제 담당자가 최종 승인 또는 반려한다.
7. 작성자는 반려된 보고서에서만 개정판을 만든다. 이전 판의 내용과 결재 이력은 보존한다.

현장 점검자 작성 보고서는 DRAFT → SUBMITTED → REVIEWED → APPROVED 순서다.
보전 팀장이 작성한 보고서는 제출 시 DRAFT → REVIEWED로 이동하며 별도의 중간 승인
기록은 만들지 않는다. REVIEWED는 최종 승인 대기를 뜻한다. 두 경로 모두 최종 승인 전에
해당 결재자가 사유와 함께 반려할 수 있다. 계정 관리자도 직책이 맞아야 하며 본인
보고서는 결재할 수 없다. 현장 책임자의 별도 결재 단계는 추가하지 않았다.

**초안 저장부터 DB에 저장된 사건 선택이 필요하다.** 사건이 없다면 저장할 수 없으며
임의 센서값이나 사건을 만들지 않는다. 사건 선택 후 첫 저장 시 보고서 번호는
`RPT-에러코드-YYYYMMDD-순번` 형식으로 발급된다. 날짜는 한국 시간의 저장일이며,
에러 코드는 연결 사건의 첫 번째 코드를 사용하며, 순번은 에러코드별·날짜별로 001부터 증가한다. 저장된 보고서의 사건은 바꿀 수 없다.
기존 보고서의 번호는 유지되고 사건 없이 저장된 기존 초안은 사건 선택 후 저장할 수 있다.
보고서 번호는 최대 64자이므로 긴 에러 코드나 공백·콜론을 포함한 에러 코드는 사용할 수 없다.
센서·사건·분석 DB 연결은 [#104 자동 분석](AUTO_ANALYSIS.md)을 켜면 동작한다. AI 분석은 연결 시점의
저장 결과를 복사해 보존한다. LLM 자동 초안 생성 연결은 #11 범위다.

제출 시 실제 조치/미수행 사유·확인 원인/미확인 사유·시험 결과/미실시 사유를 검사한다.
실제 수행이면 조치 시각이 필요하고, 미수행이면 actions_taken을 만들지 않고 사유만 남긴다.
서버는 조치 시각을 추측하지 않는다. 정지시간은 양 끝을 모두 채우거나 둘 다 비워야 한다.
사진은 기존 미리보기만 제공하고 저장·제출에는 포함하지 않는다. 영구 저장 위치는
CONTRACTS.md의 미결 사항으로 남겨두었다. 부서·후속 조치 등은 버전 JSON에 보존한다.

## 삭제와 수정 취소

- 작성자는 현재 임시 저장된 첫 버전을 삭제할 수 있다. 반려 후 작성 중인 초안은
  **수정 취소**하면 해당 초안만 삭제하고 이전 반려 판과 결재 이력을 복원한다.
- 관제 담당자는 최종 승인된 보고서 전체와 모든 버전·결재 이력을 삭제할 수 있다.
  삭제 시 벡터 DB의 검색 자료도 삭제한다. 검색 자료 삭제가 실패하면 보고서를
  유지하고 오류를 표시하므로 다시 시도할 수 있다.
- 삭제한 보고서 번호는 다시 발급하지 않는다. 번호 보관에 마이그레이션 0008이 필요하다.

## 저장 구조

마이그레이션 0004(선행 0003)는 다음 테이블을 추가한다. schema.sql은 이전 설계 참고용으로
그대로 두며 실행하지 않는다.

| 테이블 | 역할 |
|---|---|
| report | 작성자 사번(app_user FK), 사건, 상태, 현재 버전, revision, 출처·시각 |
| report_version | 버전별 폼·사건/AI 스냅샷, 제출된 MaintenanceReport 전체 JSONB |
| approval | 버전별 제출·검토·최종 승인/반려. 사번·직책·의견·시각 |
| report_index_job | 최종 승인과 같은 트랜잭션에서 만드는 색인 대기 기록(#29 연결 지점) |

미완성 입력은 ReportDraft/ReportFormData, 조회는 ReportDocument/ReportSummary를 쓴다.
제출된 MaintenanceReport의 정비 칸은 사람 입력을 변환하고, 작성자·결재 사번은 인증
계정에서 정한다. 요청 본문으로 작성자나 결재 정보를 지정할 수 없다.
AI 코드가 maintenance·approval을 작성하지 않는다.

변경마다 revision이 증가하며 저장·결재·개정에는 조회한 expected_revision을 보낸다.
다른 화면에서 먼저 수정했다면 409로 거부하므로 최신 내용을 다시 불러온다.
제출 이후 폼·사건/AI 스냅샷은 고정하고 결재 상태·이력만 추가한다.

## API

모든 경로에 Authorization: Bearer 토큰이 필요하다.

| 메서드·경로 | 기능 |
|---|---|
| GET /incidents | 보고서에 연결할 저장 사건 |
| POST /reports | 현장 점검자 또는 보전 팀장의 새 초안 |
| GET /reports?scope=mine | 본인이 작성한 보고서 |
| GET /reports?scope=review | 해당 직책의 결재 대기 |
| GET /reports/review-history | 보고서별 결재자의 최근 처리와 현재 상태 |
| GET /reports?scope=all | 직책·작성자와 무관한 전체 보고서 목록(초안·반려 포함) |
| GET /reports?scope=approved | 모든 작성자의 최종 승인 보고서 목록 |
| GET /reports/{id} | 현재 판. 모든 로그인 사용자 조회 가능 |
| GET /reports/{id}/versions/{n} | 특정 판과 결재 이력. 모든 로그인 사용자 조회 가능 |
| PUT /reports/{id}/draft | 작성자만 현재 DRAFT 저장 |
| POST /reports/{id}/submit | 작성자·현장 점검자 또는 보전 팀장 제출 |
| POST /reports/{id}/review | 보전 팀장 검토 승인 |
| POST /reports/{id}/approve | 관제 담당자 최종 승인 |
| POST /reports/{id}/reject | 해당 단계 결재자 반려. 의견 필수 |
| POST /reports/{id}/revise | 작성자가 반려 판에서 다음 DRAFT 생성 |
| DELETE /reports/{id}/draft | 작성자의 초안 삭제 또는 반려 판으로 수정 취소 |
| DELETE /reports/{id} | 관제 담당자의 최종 승인 보고서 및 검색 자료 삭제 |

POST 초안 본문은 incident_id(없으면 null), data_origin(LIVE/REPLAY/SYNTHETIC), form_data다.
PUT 초안에는 expected_revision을 추가한다. 결재·개정은 expected_revision과 선택적 comment다.
미인증 401, 권한 없음 403, 보고서/버전 없음 404, 이전 revision/상태 충돌 409,
입력 미완성 422, DB 연결·잠금 실패 503을 반환한다.

## 승인 보고서 검색 등록 (#29)

최종 승인 시 같은 DB 트랜잭션에서 `report_index_job`에 `pending`을 기록한다. API는
응답 후 백그라운드에서 이 대기 작업을 처리한다. 임베딩·벡터 저장이 끝나면
`indexed`, 실패하면 `failed`로 기록한다. 승인 자체는 검색 등록 실패와 무관하게
보존된다. 보고서에서 **최신 내용 불러오기**를 눌러 상태를 확인한다.

기존 대기 작업은 서버 재시작 뒤에도 DB에 남는다. API가 꺼져 있을 때 아래 명령으로
처리할 수 있다. 실패 작업은 원인(모델·벡터 DB 설정 등)을 해결한 뒤 명시적으로 재시도한다.

```bash
make index-reports
make index-reports ARGS=--retry-failed
```

로컬 Qdrant 폴더 모드는 한 프로세스만 열 수 있으므로 CLI로 처리할 때 API를 먼저 끈다.
Qdrant 서버 모드라면 API와 CLI가 같은 URL을 사용할 수 있다.

색인에는 **APPROVED 판**의 사건 코드와 사람이 작성한 원인 분류·확정 원인·조치·교체
부품·AI 의견 평가만 사용한다. AI가 만든 `ai_analysis`, 결재 이력, 비고·사번은
본문과 메타데이터에서 제외한다. 보고서 한 건을 청크 하나로 저장하며,
`report_id`를 문서 ID·인용 키로 사용한다. `SYNTHETIC`은 인용에 **가상 사례**라고
표시한다. 이전 정책에서 승인 후 개정된 기존 기록은 새 승인 판 색인 시 같은 문서 ID의 이전 판 벡터를 교체한다.
`pending_index_reports()`는 보고서별 최신 승인 판만 반환하고 초안·반려 판은 제외한다.

승인 보고서를 색인할 때는 실제 검색 본문과 메타데이터 확인용 Markdown도
`storage/report-previews/<보고서번호>-<식별자>/v<버전>.md`에 저장한다. 이 파일은
임베딩 벡터 자체가 아닌, 벡터로 변환한 본문과 메타데이터의 미리보기다. 보고서
삭제 시 미리보기도 함께 삭제한다. 이 기능 적용 전에 이미 색인된 보고서는 자동으로
파일이 생기지 않는다. 미리보기 저장에 실패하면 검색 등록 실패로 기록하며 재시도할 수 있다.

`data/history/synthetic_reports_v1.jsonl`의 24건은 실제 사용자가 결재한 DB 기록이
아니며 자동으로 운영 DB나 벡터 DB에 들어가지 않는다. 테스트에서 이 계약을 읽어
메모리·임시 Qdrant·Chroma 저장소에 색인하고 검색한다. 운영 흐름은 DB의 실제 승인
보고서와 outbox를 사용한다.

## 검사

```bash
uv run --no-sync pytest tests/contracts/test_report_workflow.py tests/db/test_report_repository.py tests/api/test_reports.py tests/rag/test_report_indexer.py tests/data/test_synthetic_reports.py
make check
cd hmi/web
npm run lint
npm run build
```

DB 테스트는 SQLite에서 항상 실행하고 TEST_DATABASE_URL이 있으면 PostgreSQL에서도
같은 사례를 실행한다. 테스트마다 테이블을 비우므로 별도 테스트 DB만 사용한다.
