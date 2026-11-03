# Error 자동 분석·저장·조회 (#104)

## 실행 흐름

1. `api/telemetry.py`: JSON 검증 → HistoryDetector 순차 처리 → 로컬 사건 이력 기록.
2. 자동 분석을 켰으면 `AnalysisService.ingest()`가 `db/analysis_jobs.py`에 전달한다.
   센서 1행·사건 변경·Error 분석 등록은 한 DB 트랜잭션이다. 롤백되면 ACK의
   `db_status=failed`, `agent_status=storage_failed`와 로그로 알린다. 탐지는 계속되지만
   해당 입력을 DB에 자동 재전송하지 않는다. 로컬 이력과 원본으로 누락 구간을 확인한다.
   CSV 송신기는 이 ACK에서 전송을 멈춘다.
3. Warning만으로 분석하지 않는다. 최초 Error 또는 Warning→Error에 PENDING을 만든다.
   같은 incident_id의 반복 Error·회복은 새 자동 분석을 만들지 않는다.
4. 단일 백그라운드 실행기가 RUNNING으로 선점한 뒤, 등록 시점의 Incident 스냅샷을
   `get_analyzer(get_retriever()).analyze()`에 전달한다. 수신 스레드에서 LLM을 호출하지 않는다.
5. AnalysisResult와 작업 완료를 한 트랜잭션으로 저장한다.
   OK·INSUFFICIENT_EVIDENCE → 작업 COMPLETED, 분석 FAILED → 작업 FAILED.
   실행 예외는 FAILED 작업으로 남긴다.
6. 로그인한 사용자가 결과를 조회한다. 보고서·정비·결재는 자동 작성하지 않는다.

마이그레이션 0005가 analysis_job을 추가한다. 기존 contracts는 바꾸지 않는다.
작업 ID·자동/수동 요청 키·입력 스냅샷·시각·결과 FK를 보존한다.
기존 사건·분석과 같은 저장 형식으로 작업 등록·완료를 묶는 전용 저장소를 사용한다.

## 비용 없는 터미널 시연

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONUTF8 = "1"
uv run --no-sync python scripts/demo_auto_analysis.py
```

실제 Uvicorn·WebSocket·기존 CSV 송신기·Detector·전용 SQLite를 사용한다. 가짜 Analyzer가
2초 뒤 INSUFFICIENT_EVIDENCE를 반환하므로 Claude 키·Docker·RAG 색인이 필요 없다.
8000 포트·사용자 DB를 쓰지 않는다. 결과는 outputs/analysis_demo/<실행ID>/에 남는다.
실제 분석 품질 시험이 아니라 실행·저장·비차단 흐름 시연이다.

```text
[센서 처리 #....] ... data={15필드}
[Error 진입] ... agent=등록 시도
[분석 등록] incident=INC-... job=... state=PENDING
[분석 시작] incident=INC-... job=... codes=BTT2-M10
[센서 처리 #....] ...              ← 분석 중에도 계속 수신
[분석 저장 완료] ... result=INSUFFICIENT_EVIDENCE evidence=0 elapsed=2.0s
[시연 결과] 입력=300 사건=3 분석작업=2
```

`--interval 0.5`로 송신 주기, `--analysis-delay 5`로 느린 분석을 관찰한다.

## 실제 Unreal·Claude 연결 (유료)

키·문서 색인·PostgreSQL을 준비하고 .env에 다음을 설정한다.

```dotenv
ANALYSIS_AUTO_ENABLED=true
```

기본값은 false다. true일 때 센서·사건 DB 저장과 Error 유료 호출이 켜진다.
환경 파일 변경 뒤 API를 재시작한다. 기존 WebSocket에는 인증이 없으므로 loopback 또는
접근 통제된 시연 환경에서만 사용한다. 외부 공개 전 별도 인증이 필요하다.

```powershell
uv run --no-sync --env-file .env uvicorn --app-dir src weeing_weeing.api.app:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 65536 --ws-max-queue 4 --log-level info
```

단일 API 프로세스·단일 replica만 지원한다. --reload·여러 worker를 사용하지 않는다.
Qdrant 로컬은 API와 색인 스크립트가 동시에 열지 않는다. 서버 모드는 서버 쪽 색인이 필요하다.

```powershell
uv run --no-sync python scripts/send_csv_websocket.py --context MINIMAL --interval 0.5
```

MINIMAL은 시뮬레이션 가정으로 실측 PLC 문맥이 아니다.
CSV 재생·WebSocket 재접속은 새 HistoryDetector와 새 incident_id를 만든다.
물리적으로 같은 고장인지 세션 간 병합하지 않으므로 새 유료 분석이 될 수 있다.
DB 중복 방지의 기준은 같은 incident_id와 요청 ID다.

## 조회·수동 재요청

- GET /incidents/{incident_id}/analysis: 기존 Bearer 로그인 필요.
  job(상태·작업 ID·오류 코드), analysis(최신 결과 또는 null)를 반환한다.
  새 작업 실행 중에는 이전 결과가 있을 수 있어 반드시 job 상태와 함께 표시한다.
- POST /incidents/{incident_id}/analysis/retry: 관제 담당자·보전 팀장만 가능.
  본문은 {"request_id":"클라이언트 UUID"}. 같은 HTTP 요청 재전송에는 같은 UUID를 쓴다.
  실패 작업만 재요청한다. 실행 중이면 기존 작업, 완료 뒤 새 요청은 409.
  실패 당시 입력 스냅샷으로 재실행하며 API 비용이 발생할 수 있다.
- 사건 없음 404, 미인증 401, 권한 부족 403, 비활성 503, DB 장애 503.

PowerShell 조회(기존 /auth/login으로 받은 토큰을 $token에 설정):

```powershell
$headers = @{ Authorization = "Bearer $token" }
$incidentId = "터미널에 표시된 INC-..."
Invoke-RestMethod "http://127.0.0.1:8000/incidents/$incidentId/analysis" -Headers $headers | ConvertTo-Json -Depth 12
```

## 실패·재시작 정책과 한계

- 대기/실행 최대 100개. 초과하면 사건은 저장하고 FAILED/queue_full 작업을 기록한다.
- 실패 분석은 자동 반복하지 않는다. SDK 내부 HTTP 재시도는 기존 정책을 따른다.
- PENDING은 재시작 후 처리한다. 이전 RUNNING은 FAILED/interrupted로 바꾸고 자동 재호출하지 않는다.
- 모델 응답 뒤 DB만 끊기면 메모리에 결과를 두고 저장만 재시도한다. 프로세스가 종료되면
  결과가 유실될 수 있으며 interrupted 정책을 적용한다.
- 종료 때 worker를 5초 기다린다. 진행 중 호출을 강제 취소했다고 보장하지 않는다.
- API 호출별 시간·턴 제한은 기존 설정이다. 여러 턴·SDK 재시도로 총 시간은 늘 수 있다.
  분산 실행·강제 전체 마감·취소는 별도 범위다.
- #105 센서 구간 조회·수치 대조는 [SENSOR_WINDOWS](SENSOR_WINDOWS.md)를 따른다.
  보고서 AI 초안 자동 반영과 화면 폴링은 미구현이다.
- 새 로그에는 예외 원문·키·LLM 원문을 기록하지 않는다.
