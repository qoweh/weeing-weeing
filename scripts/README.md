# scripts

## RAG 색인 (`build_index.py`)

`data/catalog.toml`에 적힌 문서와 벡터 DB를 맞춘다. 바뀐 문서만 다시 색인하고, 목록에서 빠진 문서는 지운다.
설정은 `.env`(`VECTOR_STORE`, `EMBEDDING_MODEL`, `QDRANT_*`, `CHROMA_DIR`)를 읽는다.

```bash
make index                  # = PYTHONPATH=src uv run --no-sync python scripts/build_index.py
make index ARGS=--dry-run   # 무엇이 바뀔지만 출력. 모델을 올리지 않는다
make index ARGS=--force     # 바뀌지 않은 문서도 다시 색인 (청킹·파서를 바꿨을 때)
make index ARGS=--recreate  # 컬렉션을 새로 만들고 전부 색인 (임베딩 모델·차원·토크나이저를 바꿨을 때)
```

결과는 added/updated/unchanged/removed/failed 표로 나온다. 종료 코드는 0 성공, 1 실패한 문서 있음, 2 설정·잠금·Indexer 문제로 시작 못 함.
실제 색인은 #6 Indexer(파싱·청킹)가 `rag/factory.py`의 `indexer_class`에 연결된 뒤 동작한다. 그 전에는 `--dry-run`만 쓸 수 있다.
`--recreate`는 카탈로그 밖에서 들어온 문서(승인 보고서)도 지우므로 그것도 다시 넣어야 한다.

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
