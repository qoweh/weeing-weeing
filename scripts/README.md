# scripts

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
