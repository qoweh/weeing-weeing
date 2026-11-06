# data

원본은 고치지 않는다. 가공한 결과물은 새 파일 이름으로 만들고 아래 표에 추가한다.

| 경로 | 내용 | 출처 |
|---|---|---|
| `faq/service_v1.toml` | 이용 안내 5개·직책별 문의 안내 2개. 항목별 버전·검토일·근거·활성 상태를 보존하며 LLM 없이 ID로 조회 | 사용자 지정 `docs/AUTH.md`·`docs/REPORTS.md` 및 코드 대조 (#87). 현장 책임자 제외 합의 반영, 개인 연락처는 추정하지 않음 |
| `eval/llm_cases_v1.toml` | LLM 구조화 출력 점검 사례 4개(근거 있음 2·없음 1·관련 없음 1). 근거 문장은 `parsed/`의 매뉴얼·룰에서 줄여 옮김 | 직접 작성 (#10) |
| `eval/incident_p03_demo.json` | 에이전트 실행 예시 사건(BTT2-P03 입구 장기 점유, 가상). `make analyze` 기본 입력 | 직접 작성 (#102) |
| `eval/rag_queries_v1.toml` | RAG E2E 검증용 샘플 질의 12개(기대 문서 + 기대 키워드). 키워드는 `parsed/`에서 해당 문서에 있는지 확인함 | 직접 작성 (#28) |
| `seed/documents_v1.toml` | 서버·로컬에 미리 등록할 팀 문서 3개(매뉴얼·룰·규정)의 문서 ID·종류·설비 ID·경로. `make seed-docs`가 웹 업로드와 같은 방식으로 등록하고, 이미 임베딩된 같은 파일은 건너뜀 | 직접 작성 (D-32) |
| `seed/demo_users_v1.toml` | 시연용 계정 5개(관리자 1 + 직책 4종). 가상 인물, 비밀번호 없음. `make seed-users`가 사용 | 직접 작성 (#62) |
| `history/synthetic_reports_v1.jsonl` | 8개 주요 코드별 3건씩 총 24건의 승인된 가상 정비 이력. `MaintenanceReport` 계약을 따르며 #29 RAG 색인·검색과 Agent 사례 비교 시험에 사용. `scripts/generate_synthetic_reports.py`로 재생성 | BTT-MANUAL v2.0의 점검·조치 범위를 바탕으로 작성한 **합성 사례** (#30, 실측·실제 승인 아님) |
| `eval/rag_documents_v1.toml` | 검색 평가용 PDF 자료 목록. 임시 평가 저장소에서만 사용하고 운영 DB에는 등록하지 않음 | 직접 작성 (#28) |
| `telemetry/battery_tray_transfer_telemetry_v3_15cols.csv` | Telemetry v3 원본 60행(1초 간격). 전류·외함 온도는 전부 빈 값. SHA-256 `66f2ee2e…381a6` | 노션 1차 분담 최종 문서 |
| `rulebase/BTT-RULE_v2.0.pdf` | 룰베이스 최종 정의서 BTT-RULE v2.0 (코드 31개, 임계값, 사건 저장 계약) | 노션 1차 분담 최종 문서 |
| `manuals/BTT-MANUAL_v2.0.pdf` | 에러코드·대응 매뉴얼 BTT-MANUAL v2.0 | 노션 1차 분담 최종 문서 |
| `regulations/BTT-SOP-001.pdf` | 사내 규정·SOP BTT-SOP-001 (조문형, 승인 전 초안) | 노션 1차 분담 최종 문서 |
| `templates/maintenance_report_form_v1.2.pdf` | 정비 보고서 양식 CONV-MR-S-001 v1.2 | 노션 1차 분담 최종 문서 |

- 평가용 PDF는 `manuals/`, `rulebase/`, `regulations/`에 종류별로 분류한다. 운영 문서는 웹에서 등록하며, 청크 미리보기는 업로드 폴더의 `chunks.md`에서 확인한다. 기존 청킹과 구조 기반 청킹 비교 방법은 [청킹 비교 안내](../docs/CHUNKING_COMPARISON.md)를 참고한다.
- 운영 문서는 사이트의 매뉴얼 등록·목록에서 관리한다. 등록된 다른 문서와 파일 해시가 같으면 중복 등록을 거부한다.
- 화면(HMI)에서 올린 문서는 git 밖 `storage/uploads/`에 원본이, DB `document` 테이블에 정보와 상태가 저장된다. 웹 등록 시 검색 자료를 자동 생성한다. 여기에 보관한 팀 PDF 원본은 자동 등록되지 않는다. 미리 등록하려면 `make seed-docs`(서버 `ops/aws.sh seed-docs`)를 실행한다.
- 모든 수치는 시연용 합성·지정값이다. 실제 설비 진단 근거로 쓰지 않는다(정의서 1절).
- 합성 정비 이력의 AI 분석 칸도 `model=synthetic/example`인 예시이며 실제 모델 실행 결과가 아니다. 정비 조치·결재 사번 `SYN-*`도 모두 가상이다. 사례 정의를 바꾸면 `PYTHONPATH=src uv run --no-sync python scripts/generate_synthetic_reports.py`로 JSONL을 재생성하고 `uv run --no-sync pytest tests/data/test_synthetic_reports.py`로 검증한다.
- 큰 파일(수십 MB 이상)이나 개인정보는 커밋하지 않는다.

## 미래 Error ML 첫 실험

| 경로 | 내용 | 출처 |
|---|---|---|
| `eval/ml_future60_v1/` | 원본 검증, 고정 실행 분리, window 집계, 검증 후보, 메타데이터, 평가 및 시험 혼동행렬. 원본 센서 행은 포함하지 않음 | 사용자 제공 Unreal 합성 `conveyor_dataset.csv`, SHA-256 `26ed78c3…3086a1`; [실험 설명](../docs/ML_FUTURE_ERROR.md) |

15종 고장 통합 재학습의 검증·실행 분리·평가·혼동행렬은 `eval/ml_future60_v2_15faults/`에 있다. 두 사용자 제공 Unreal CSV(총 138,194행)의 집계이며 원본 센서 행은 포함하지 않는다. [확장 학습 안내](../docs/ML_EXPANDED_TRAINING.md)를 참고한다.

원본 CSV는 저장소 밖 실제 경로에서 읽으며 수정·Git 추가하지 않는다.
모델 joblib과 행별 예측은 Git 제외 `outputs/ml/`에 저장한다.
