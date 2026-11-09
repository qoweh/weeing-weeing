# 문서 안내

RAG·챗봇 작업은 구현 설명, 실행 방법, 평가 결과, 사건별 승인 정답으로 나누어
관리한다. 같은 결과를 날짜별 진행 문서에 반복하지 않고 아래 주제 문서를 갱신한다.
이번 정리는 저장소에 있는 작업·검토·사용자 실행 기록의 통합이며 새 성능 측정이 아니다.

## RAG·챗봇 작업 문서

| 목적 | 문서 | 담는 내용 |
|---|---|---|
| 검색 구현 | [RAG 색인·검색](RAG_RETRIEVAL.md) | 변경 감지·청킹·Dense/BM25·리랭킹·근거·문서 관리 |
| 검색 평가 실행 | [RAG 평가 방법](RAG_EVALUATION_GUIDE.md) | 청킹·검색·하한·챗봇 근거 부족 평가 도구와 조건 |
| 측정 결과 | [RAG 성능 평가](rag_e2e/README.md) | 검색·리랭킹·청킹·새 질문·독립 질문 실측 |
| 사건 정답 | [E2E 승인 사례](RAG_E2E_CASES.md) | 합성 10사례의 입력과 사람 승인 정답 v1 |
| 출처·원문 | [E2E 근거](RAG_E2E_SOURCES.md) | PDF 버전·쪽·해시·수치·기존 사례·청크 대조 |
| 재현 준비 | [E2E 스냅샷](RAG_E2E_SNAPSHOT.md) | 평가 환경·87청크 저장 확인·fixture 계약·백업/복원·집계 |
| 챗봇 동작 | [챗봇 구현](CHATBOT.md) | FAQ·자유 질문·이력/사건 조회·근거 검토·건수 전용·왕복 감소 |
| API·화면·저장 | [HTTP·화면](CHAT_API.md), [대화 저장](CHAT_STORAGE.md) | 인증·본인 대화·중복 요청·상태·전송 |
| 챗봇 평가 실행 | [챗봇 평가 방법](CHAT_EVALUATION.md) | 5문항 프롬프트 A/B·10문항 왕복 비교·계측·사람 검수 |
| 챗봇 실측 | [왕복 비교 결과](CHAT_ROUNDTRIP_RESULTS.md) | 2026-11-05 v9 비교의 40요청·질문별 수치·측정 조건 |

## 작업 내용 정리

- **근거 검색:** 문서 색인·문서별 갱신, 한국어 하이브리드 검색, 리랭킹·관련도 필터,
  문서·버전·쪽을 포함한 근거 반환을 구현·연결했다.
- **검색 평가:** 청킹·리랭킹 전후·하한·새 질문을 비교하고, 질문별 순위·빈 결과·
  문맥 키워드 영향을 구분해 검토했다.
- **사건 평가 자료:** 8개 어려운 판단 유형을 바탕으로 E01~E10을 작성하고,
  PDF·센서 조건·승인 정답·기존 평가와의 차이·스냅샷 절차를 정리했다.
- **평가 환경 준비:** 사용자 기록에 따라 PostgreSQL·Qdrant 준비, 스키마·청크 수·
  페이지 메타데이터와 9사례 적재기의 로컬 검증 범위를 정리했다.
- **챗봇 연결:** FAQ와 자유 질문, 문서/승인 이력/사건 조회, 조건·출처·응답 검토,
  개인 대화·중복 요청과 건수 전용·검토 본문 중복 제거 경로를 정리했다.
- **챗봇 평가:** 과거 왕복 실측과 현재 프롬프트 A/B 방법을 분리하고,
  호출·검토·지연·토큰·동일 상태 쌍·사람 검수 기준을 남겼다.

구현 연결, 가짜 모델 검사, 실제 검색 실측, 사용자 실행 응답
검토, 운영 배포는 각 문서에 기록된 증거 범위로 구분한다.

## 보완할 사항

검색 성능의 보완 과제는 [평가 안내](rag_e2e/README.md)의 표에서 관리한다.
나머지 작업은 아래 항목만 추가로 기록한다.

| 대상 | 보완할 내용 | 완료 확인 자료 |
|---|---|---|
| E2E fixture | E08 NDE 결손의 계약상 표현, E05 합성 승인 보고서, E07 가상 구버전, 실제 평가 DB 적재 | 승인 의미를 유지한 fixture·적재 건수·충돌 검사 |
| E2E 재현 | 실제 데이터와 벡터 색인의 영속 백업·별도 대상 복원·본문 해시·상태 대조 | snapshot ID·백업 해시·복원 비교 |
| 멀티 분석 | 고정 자료에서 실제 검색·센서 조회를 거치는 사례별 실행·판정 | 완료/보류/실행 오류를 분리한 유형별 결과 |
| 챗봇 v13 | 건수 전용 종료·중복 본문 공유를 실제 호출 기록과 사람 답변 검수로 확인 | 목적/도구/출처·호출·지연·품질 검토 |
| 통합·운영 | 현재 판·승인/삭제·대화 저장·화면 전송을 경로별로 검증하고 배포 SHA 확인 | 자동 검사·화면 결과·배포 기록 |

과거 준비 오류·중단 과정을 현재 미완료 항목으로 반복하지 않는다.
유효한 낮은 성능·순위 변화·보류 조건은 결과에서 지우거나 성공으로 바꾸지 않는다.
실제 인증·유료 API는 사용자가 자기 터미널에서 실행하고 자동 검증에는 가짜
클라이언트만 사용한다. 비밀 보호 설정은 아래 보안 문서를 따른다.

## 공통 설계·개발·보안

| 분야 | 문서 |
|---|---|
| 구조·계약 | [ARCHITECTURE](ARCHITECTURE.md), [CONTRACTS](CONTRACTS.md), [DECISIONS](DECISIONS.md) |
| 개발·변경 절차 | [LOCAL_SETUP](LOCAL_SETUP.md), [CHANGE_WORKFLOW](CHANGE_WORKFLOW.md) |
| 모델 구성 | [EMBEDDING_API](EMBEDDING_API.md), [COMMERCIAL_MODELS](COMMERCIAL_MODELS.md), [DIRECTION_CHANGES](DIRECTION_CHANGES.md) |
| 보안·추적 | [AI_DATA_SECURITY](AI_DATA_SECURITY.md), [USAGE_TRACKING](USAGE_TRACKING.md), [비밀 읽기 보호](security/SECRET_GUARD_SETUP.md), [Claude 보호](security/CLAUDE_SECRET_GUARD_SETUP.md) |

## 다른 모듈의 전문 문서

공통 구조와 다른 모듈의 상세 문서는 기존 책임·계약을 유지한다.

| 분야 | 문서 |
|---|---|
| 분석 Agent | [AGENT](AGENT.md), [멀티 분석](MULTI_AGENT_ANALYSIS.md), [역할 프롬프트](MULTI_AGENT_PROMPTS.md), [LLM 평가](LLM_EVALUATION.md) |
| 사건·센서 | [DETECTOR_RULES](DETECTOR_RULES.md), [INCIDENT_HISTORY](INCIDENT_HISTORY.md), [SENSOR_WINDOWS](SENSOR_WINDOWS.md), [AUTO_ANALYSIS](AUTO_ANALYSIS.md) |
| 입력·연동 | [JSON_INPUT](JSON_INPUT.md), [WEBSOCKET_TELEMETRY](WEBSOCKET_TELEMETRY.md), [UNREAL_STATE_CONTEXT](UNREAL_STATE_CONTEXT.md) |
| DB·보고서·인증 | [DB](DB.md), [REPORTS](REPORTS.md), [MAINTENANCE_SEED](MAINTENANCE_SEED.md), [AUTH](AUTH.md) |
| 화면 | [DASHBOARD_3D](DASHBOARD_3D.md), [CCTV_WEBRTC](CCTV_WEBRTC.md), [DESKTOP_SCENARIOS](DESKTOP_SCENARIOS.md) |
| 운영·AWS | [DEPLOY](DEPLOY.md), [AWS_ACCESS](AWS_ACCESS.md), [AWS_TELEMETRY](AWS_TELEMETRY.md), [TELEMETRY_RETENTION](TELEMETRY_RETENTION.md) |
| 예측 실험 | [ML_FUTURE_ERROR](ML_FUTURE_ERROR.md), [평가 결과](ML_FUTURE_ERROR_RESULTS.md), [실시간 연결](ML_LIVE.md), [확장 학습](ML_EXPANDED_TRAINING.md) |
