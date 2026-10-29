# data

원본은 고치지 않는다. 가공한 결과물은 새 파일 이름으로 만들고 아래 표에 추가한다.

| 경로 | 내용 | 출처 |
|---|---|---|
| `eval/llm_cases_v1.toml` | LLM 구조화 출력 점검 사례 4개(근거 있음 2·없음 1·관련 없음 1). 근거 문장은 `parsed/`의 매뉴얼·룰에서 줄여 옮김 | 직접 작성 (#10) |
| `eval/incident_p03_demo.json` | 에이전트 실행 예시 사건(BTT2-P03 입구 장기 점유, 가상). `make analyze` 기본 입력 | 직접 작성 (#102) |
| `eval/rag_queries_v1.toml` | RAG E2E 검증용 샘플 질의 12개(기대 문서 + 기대 키워드). 키워드는 `parsed/`에서 해당 문서에 있는지 확인함 | 직접 작성 (#28) |
| `seed/demo_users_v1.toml` | 시연용 계정 5개(관리자 1 + 직책 4종). 가상 인물, 비밀번호 없음. `make seed-users`가 사용 | 직접 작성 (#62) |
| `history/synthetic_reports_v1.jsonl` | 8개 주요 코드별 3건씩 총 24건의 승인된 가상 정비 이력. `MaintenanceReport` 계약을 따르며 #29 RAG 색인·검색과 Agent 사례 비교 시험에 사용. `scripts/generate_synthetic_reports.py`로 재생성 | BTT-MANUAL v2.0의 점검·조치 범위를 바탕으로 작성한 **합성 사례** (#30, 실측·실제 승인 아님) |
| `catalog.toml` | RAG 기준 문서 목록(문서 ID·버전·종류·상태·경로). `make index`가 DB 문서 목록에 seed로 반영하고 벡터 DB를 맞춘다 | 직접 작성 (#26) |
| `telemetry/battery_tray_transfer_telemetry_v3_15cols.csv` | Telemetry v3 원본 60행(1초 간격). 전류·외함 온도는 전부 빈 값. SHA-256 `66f2ee2e…381a6` | 노션 1차 분담 최종 문서 |
| `rulebase/BTT-RULE_v2.0.pdf` | 룰베이스 최종 정의서 BTT-RULE v2.0 (코드 31개, 임계값, 사건 저장 계약) | 노션 1차 분담 최종 문서 |
| `manuals/BTT-MANUAL_v2.0.pdf` | 에러코드·대응 매뉴얼 BTT-MANUAL v2.0 | 노션 1차 분담 최종 문서 |
| `regulations/BTT-SOP-001.pdf` | 사내 규정·SOP BTT-SOP-001 (조문형, 승인 전 초안) | 노션 1차 분담 최종 문서 |
| `templates/maintenance_report_form_v1.2.pdf` | 정비 보고서 양식 CONV-MR-S-001 v1.2 | 노션 1차 분담 최종 문서 |

- PDF는 `manuals/`, `rulebase/`, `regulations/`에 종류별로 분류한다. 현재 임시 색인 스크립트는 `manuals/BTT-MANUAL_v2.0.pdf`를 사용한다. 문서가 바뀌면 버전이 드러나는 새 파일 이름으로 넣는다(인용 문자열에 버전이 들어가기 때문).
- 색인할 문서를 추가·교체하면 `catalog.toml`도 고친다. 같은 내용의 파일을 두 항목으로 넣으면 검증에서 막힌다.
- 화면(HMI)에서 올린 문서는 여기가 아니라 git 밖 `storage/uploads/`에 원본이, DB `document` 테이블에 상태가 저장되고, `make index`가 카탈로그 문서와 함께 관리한다.
- 모든 수치는 시연용 합성·지정값이다. 실제 설비 진단 근거로 쓰지 않는다(정의서 1절).
- 합성 정비 이력의 AI 분석 칸도 `model=synthetic/example`인 예시이며 실제 모델 실행 결과가 아니다. 정비 조치·결재 사번 `SYN-*`도 모두 가상이다. 사례 정의를 바꾸면 `PYTHONPATH=src uv run --no-sync python scripts/generate_synthetic_reports.py`로 JSONL을 재생성하고 `uv run --no-sync pytest tests/data/test_synthetic_reports.py`로 검증한다.
- 큰 파일(수십 MB 이상)이나 개인정보는 커밋하지 않는다.
