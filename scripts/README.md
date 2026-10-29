# scripts

## Error 자동 분석 시연 (#104)

`PYTHONPATH=src uv run --no-sync python scripts/demo_auto_analysis.py`는 실제 WebSocket과
SQLite·가짜 Analyzer로 입력→Error→작업 등록→분석→저장을 시연한다. Claude 비용은 없다.
PowerShell 명령과 실제 유료 연결은 [AUTO_ANALYSIS](../docs/AUTO_ANALYSIS.md)를 따른다.

## 모델 받기 (`download_models.py`)

`.env`의 `EMBEDDING_MODEL`·`RERANKER_MODEL`을 Hugging Face 캐시에 받는다. LLM은 상용 API라 받을 것이 없다. 검색·리랭킹은 실행 중에 모델을 내려받지 않으므로 새 PC에서 `make index` 전에 한 번 실행한다. 이미 받은 모델은 확인만 하고 넘어간다.

```bash
make models                     # = PYTHONPATH=src uv run --no-sync python scripts/download_models.py
```

종료 코드는 0 모두 받음, 1 받지 못한 모델 있음.

## 시연 계정 (`seed_users.py`, #62)

`data/seed/demo_users_v1.toml`의 계정(관리자 `ADMIN` + 직책 4종)을 DB에 만든다. 이미 있는 사번은 건드리지 않는다. 로그인·권한은 [docs/AUTH.md](../docs/AUTH.md).

```bash
make seed-users                          # 계정마다 임의 비밀번호를 한 번만 출력
make seed-users ARGS=--ask-password     # 모든 시연 계정을 같은 비밀번호로(입력받음, 8자 이상)
```

종료 코드는 0 성공, 2 DB 연결 실패·비밀번호 규칙 위반.

## RAG 색인 (`build_index.py`)

DB의 문서 목록(`document` 테이블)과 벡터 DB를 맞춘다. 순서는
`data/catalog.toml`(git)을 DB에 seed로 반영 → DB 목록(seed + 화면에서 올린 완료된 업로드) 색인 → 결과를 DB에 기록.
바뀐 문서만 다시 색인하고, 목록에서 빠진 문서는 지운다. 업로드 API도 같은 Indexer·저장소를 쓴다.
설정은 `.env`(`DATABASE_URL`, `VECTOR_STORE`, `EMBEDDING_MODEL`, `QDRANT_*`, `CHROMA_DIR`, `RAG_CATALOG`, `UPLOAD_DIR`)를 읽는다.
**DB가 필요하다**: `make db-up`, 또는 Docker 없이 `.env`에 `DATABASE_URL=sqlite:///storage/dev.db`([LOCAL_SETUP 3절](../docs/LOCAL_SETUP.md)).

언제 쓰나: 서비스 기능이 아니라 관리 명령이다. 새 PC·서버를 처음 세팅할 때, 기준 문서를 바꿨을 때, 임베딩 모델을 바꿨을 때(`--recreate`), 배포할 때.

```bash
make index                  # = PYTHONPATH=src uv run --no-sync python scripts/build_index.py
make index ARGS=--dry-run   # 무엇이 바뀔지만 출력. 모델을 올리지 않고 DB 내용도 바꾸지 않는다(스키마만 최신으로)
make index ARGS=--force     # 바뀌지 않은 문서도 다시 색인 (청킹·파서를 바꿨을 때)
make index ARGS=--recreate  # 컬렉션을 새로 만들고 전부 색인 (임베딩 모델·차원·토크나이저를 바꿨을 때)
```

결과는 added/updated/unchanged/removed/failed 표로 나온다. 종료 코드는 0 성공, 1 실패한 문서 있음, 2 설정·DB 연결·잠금·Indexer 문제로 시작 못 함.
업로드 항목에 문제가 있으면(파일 없음, 카탈로그와 doc_id·내용이 겹침) 그 항목만 건너뛰고 `경고:`로 알린다. 카탈로그에 새로 넣은 문서와 doc_id가 같은 업로드는 대체(superseded)된다. 카탈로그(`data/catalog.toml`) 문제는 종료 코드 2로 멈춘다.
#58 이전 방식의 업로드(`storage/uploads/<id>/metadata.json`)는 첫 `make index`가 DB로 옮기고 파일 이름을 `metadata.json.imported`로 바꾼다.
`--recreate`는 업로드 문서도 목록에 있으므로 함께 다시 색인한다. 목록 밖에서 들어온 문서(승인 보고서, #29)는 지워지므로 다시 넣어야 한다.
API 서버가 Qdrant 로컬 폴더를 열고 있으면 `make index`는 잠금 오류로 멈춘다(종료 코드 2). API를 끄거나 `QDRANT_URL` 서버 모드를 쓴다.

## RAG E2E 검증 (`verify_rag_e2e.py`, #28)

카탈로그 문서를 백엔드마다 **새 임시 저장소**에 색인하고 아래를 확인한다. `storage/`의 실제 색인은 건드리지 않는다.

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

사건 JSON 하나를 사건 분석 에이전트로 분석한다. Claude가 `search_evidence` 도구로 근거를 찾고 `submit_analysis`로 결과를 낸다. 색인(`make index`)과 API 키가 필요하다. DB에는 저장하지 않는다.

```bash
make analyze                                     # data/eval/incident_p03_demo.json
make analyze ARGS="--incident 사건.json"
```

- 출력: `AnalysisResult` JSON, 도구 호출 기록, 토큰 수
- 종료 코드 0 OK·INSUFFICIENT_EVIDENCE / 1 FAILED / 2 입력·설정 문제

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
