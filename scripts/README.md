# scripts

## .env 점검 (`check_env.py`)

`make env-check`는 내 `.env`를 `.env.example`과 비교해 고칠 것(중복·형식 오류·빈 `ANTHROPIC_API_KEY`·셸 값 충돌), 예전 변수, 주석이라 적용 안 되는 변수, 기본값을 쓰는 변수, 기본값과 다른 값을 보여 준다. 비밀 값(키·비밀번호·토큰·`DATABASE_URL`)은 "설정됨/비어 있음"만 표시한다. `.env`를 환경변수로 불러오지 않고 파일만 읽는다. 종료 코드 0 고칠 것 없음 / 1 있음 / 2 파일 없음. 서버 점검 명령은 [DEPLOY](../docs/DEPLOY.md#3-서버-env).

## Error 자동 분석 시연 (#104)

`PYTHONPATH=src uv run --no-sync python scripts/demo_auto_analysis.py`는 실제 WebSocket과
SQLite·가짜 Analyzer로 입력→Error→작업 등록→분석→저장을 시연한다. Claude 비용은 없다.
PowerShell 명령과 실제 유료 연결은 [AUTO_ANALYSIS](../docs/AUTO_ANALYSIS.md)를 따른다.

## 시연 계정 (`seed_users.py`, #62)

`data/seed/demo_users_v1.toml`의 계정(관리자 `ADMIN` + 직책 4종)을 DB에 만든다. 이미 있는 사번은 건드리지 않는다. 로그인·권한은 [docs/AUTH.md](../docs/AUTH.md).

```bash
make seed-users                          # 계정마다 임의 비밀번호를 한 번만 출력
make seed-users ARGS=--ask-password     # 모든 시연 계정을 같은 비밀번호로(입력받음, 8자 이상)
```

종료 코드는 0 성공, 2 DB 연결 실패·비밀번호 규칙 위반.

## 웹 문서 등록·관리

문서는 HMI의 **문서 등록 / 문서 목록**에서 관리한다. 관제 담당자가 PDF를 등록하면 DB에 접수 정보를 저장하고 파싱·청킹·임베딩·벡터 저장까지 자동으로 진행한다. 다른 문서 ID에 같은 파일 해시가 있으면 중복 등록을 거부한다.

문서 버전은 PDF 파일명의 `v1.0`, `v2.0` 같은 표기에서 자동으로 정한다(대문자 `V`도 지원). 표기가 없으면 `1.0`이다. 화면에서는 읽기 전용으로 표시하며 서버도 파일명으로 결정하므로 별도로 전송한 버전 값은 사용하지 않는다. 예: `BTT-MANUAL_v2.0.pdf` → `2.0`, `설비 매뉴얼.pdf` → `1.0`.

문서 목록 검색은 제목·문서 ID·설비 ID와 PDF에서 추출된 본문을 함께 검색한다(`GET /documents?q=검색어`, 최대 200자). 본문에 일치하면 주변 문장 일부를 표시한다. 서버가 현재 등록된 업로드의 `parsed.md`를 읽는 키워드 검색이며, LLM·임베딩·벡터 DB 연결은 필요 없다. 줄바꿈 등 연속 공백을 정리하고 영문 대소문자를 구분하지 않는다. 이전 판·삭제된 문서는 검색 대상에서 제외하며, 추출 파일이 없거나 읽을 수 없으면 해당 문서는 제목·ID·설비 ID로만 검색된다. 현재 방식은 요청마다 본문 파일을 읽으므로 문서가 많아지면 별도 본문 검색 색인으로 전환한다.

삭제 확인 후 벡터 청크를 제거하고 PostgreSQL 문서 행도 실제 삭제한다. 실패 시 재시도 상태를 남긴다. 삭제한 PDF가 필요해지면 웹에서 다시 올린다. 원본 파일은 업로드 폴더에 보관한다.

운영 카탈로그와 `make index`·일괄 색인 스크립트는 제거했다. `make rag-e2e`는 평가용 문서 목록으로 임시 저장소만 만들어 검색 품질을 검사하며 실제 DB에 문서를 등록하지 않는다.

## RAG E2E 검증 (`verify_rag_e2e.py`, #28)

`data/eval/rag_documents_v1.toml`의 평가 문서를 백엔드마다 **새 임시 저장소**에 색인하고 아래를 확인한다. `storage/`의 실제 색인은 건드리지 않는다.

| 검사 | 통과 조건 |
|---|---|
| 색인 | 모든 문서가 added, 실패 없음 |
| 멱등 | 한 번 더 실행하면 전부 unchanged |
| 갱신 | 첫 문서의 버전만 올리면 그 문서만 updated, 옛 버전 청크 0 |
| 검색 비교 | `data/eval/rag_queries_v1.toml` 질의를 dense·hybrid로 실행해 hit@1·hit@k·MRR을 표로 남김. `RERANKER_MODEL`이 있으면 공개 검색기의 reranked 결과도 비교(통과 기준 없음) |

```bash
make rag-e2e                                                    # Qdrant 로컬 + Chroma
make rag-e2e ARGS="--backends qdrant,chroma,qdrant-server"      # 서버도 (make qdrant-up, QDRANT_URL 먼저)
```

결과는 `outputs/rag_e2e/report-<시각>.md`에 남는다. 공식 측정 결과와 해석은 [docs/RAG_E2E.md](../docs/RAG_E2E.md)에 날짜별로 남긴다. 종료 코드는 0 통과, 1 검사 실패, 2 시작 못 함(설정·Indexer).
#6 Indexer가 `rag/factory.py`의 `indexer_class()`에 연결돼야 실행된다. 그 전에는 종료 코드 2로 안내한다.

## LLM 점검 (`check_llm.py`, #101)

Claude가 구조화 출력(JSON 스키마)과 근거 인용 규칙을 지키는지 `data/eval/llm_cases_v1.toml` 사례로 점검한다. 근거를 고정하므로 검색 품질과 무관하게 LLM 판단만 잰다. `ANTHROPIC_API_KEY`가 필요하고 사례마다 API를 한 번 부른다.

```bash
make llm-check                                                # .env의 LLM_MODEL
make llm-check ARGS="--model claude-sonnet-5-5 --repeat 3"    # 모델 비교
make llm-check ARGS="--effort low"                            # 생각 깊이 비교
```

- 반드시 통과: JSON → 분석 초안 스키마 → 제출 검사(`analyst.check_draft`) → `AnalysisResult` 계약
- 숫자로 기록: 기대 상태(OK / INSUFFICIENT_EVIDENCE) 일치, 사례당 시간, 토큰 수
- 보고서: `outputs/llm_check/report-<시각>.md`. 종료 코드 0 통과 / 1 실패 사례 있음 / 2 키·모델·설정 문제

## 사건 분석 에이전트 (`analyze_incident.py`, #102)

사건 JSON 하나를 사건 분석 에이전트로 분석한다. Claude가 `search_evidence` 도구로 근거를 찾고 `submit_analysis`로 결과를 낸다. 검색 자료와 API 키가 필요하다. 기본은 DB 미저장이며 아래 옵션으로 기존 사건에 저장할 수 있다.

```bash
make analyze                                     # data/eval/incident_p03_demo.json
make analyze ARGS="--incident 사건.json"
```

- 출력: `AnalysisResult` JSON, 도구 호출 기록, 토큰 수
- 종료 코드 0 OK·INSUFFICIENT_EVIDENCE / 1 FAILED / 2 입력·설정 문제

`--ask-key`는 사용자가 직접 연 터미널에서 API 키를 숨김 입력한다. IDE 자동 문맥에
열린 파일이 포함될 수 있으므로 키를 편집기·채팅·명령 인자에 넣지 않는다.
`uv run --no-sync --no-env-file`로 실행하면 `.env`를 자동 로드하지 않는다.
`--result-out 새파일.json`은 결과를 별도로 보존하고 기존 파일이 있으면 호출 전에 멈춘다.
`--save-db`는 현재 DB에 같은 공정·설비의 사건이 있을 때 분석 결과와 입력 스냅샷을
완료 작업으로 함께 추가한다. 대기·실행 중인 분석이 있으면 유료 호출 전에 중단한다.
이 옵션에는 `--result-out`이 필수이며, 결과 파일 저장 후 DB 저장을 시도한다.
사건 회복·승인 상태와 정비·결재 칸은 바꾸지 않는다. 저장 전용 API에서도 기존
분석 조회로 확인할 수 있으며, 자동 분석이나 백그라운드 worker를 켤 필요가 없다.
단건 분석도 여러 도구·LLM 호출로 구성되어 비용이 발생한다. DB 저장 실패 후에는
보존된 결과 파일을 확인하고 유료 분석을 자동 반복하지 않는다.

## 사건 센서 이력 저장

기존 스냅샷 데모와 별도로 `demo_incident_history.py`를 사용한다.
입력 CSV, 출력 경로, 대상 룰, RUN_ONLY/MINIMAL 시뮬레이션 문맥을 지정할 수 있다.
실행 후 저장 이력을 다시 검증하고 사건별 행 수와 실제 파일 크기를 출력한다.

```bash
uv run --no-sync python scripts/demo_incident_history.py --csv data/telemetry/battery_tray_transfer_5min_warning_error_v4.csv --context MINIMAL
```

저장 형식·조회 API·버퍼·실패 중단 정책: [INCIDENT_HISTORY](../docs/INCIDENT_HISTORY.md).

한 번씩 돌리는 보조 스크립트를 둔다(합성 데이터 생성, RAG 색인 실행, 시드 데이터 등).

- 실행: `uv run python scripts/<이름>.py`
- 다시 써도 되는 로직은 `src/weeing_weeing/` 쪽으로 옮기고, 여기에는 실행 진입점만 남긴다.
- 파일 맨 위 주석에 무엇을 하는지, 입력·출력 경로를 적는다.

## Incident JSON 출력 시연

저장소 루트에서 실행한다.

```bash
uv run --no-sync python scripts/demo_incident_json.py
```

원본 CSV 센서값에 가짜 룰 판정을 붙여 확정·지속·회복 JSON을 화면에 출력하고,
`outputs/incidents/<사건 ID>/`에 아래 세 파일을 UTF-8로 저장한다.

| 파일 | 확인할 내용 |
|---|---|
| `01_confirmed.json` | 20초 후보 시작, 23초 확정, 설비·룰·센서 근거 |
| `02_updated.json` | 같은 사건 ID 유지, 마지막 감지 시각 29초로 갱신 |
| `03_recovered.json` | `RECOVERED` 전환, 회복 시각 30초, 마지막 이상 시각은 29초 유지 |

위 시각은 시연용 가정으로 실제 임계값·지속 조건을 검증하지 않는다.
센서 근거는 각 이상 시점의 전체 센서값을 담고, 결측값은 `null`, `valid=false`로 표시한다.
회복 JSON의 센서 근거는 마지막 이상 시점인 29초의 값을 보존한다.
각 파일은 `Incident` 하나이며 `Incident.model_validate_json()`으로 다시 읽을 수 있다.
재실행하면 새 사건 ID의 폴더가 생긴다. 산출물은 Git에서 제외되며 Agent 호출은 포함하지 않는다.

## CSV WebSocket 테스트 송신기

서버를 켜둔 뒤 `uv run --no-sync python scripts/send_csv_websocket.py --context MINIMAL`로
v4 CSV를 전송한다. 서버 실행·옵션·응답 규격은 [WebSocket 안내](../docs/WEBSOCKET_TELEMETRY.md)를 따른다.
