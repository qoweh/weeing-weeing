# WebSocket 센서 수신과 CSV 테스트 송신기

Unreal 없이도 CSV로 실제 WebSocket 전송을 시험할 수 있다.

```text
CSV 송신기 / Unreal
  → ws://localhost:8000/ws/telemetry
  → JsonTelemetryInput (parse_telemetry_json)
  → 같은 HistoryDetector에 순차 전달
  → 이력 저장 후 처리 응답
  → Error 최초 진입 표시 → 선택적 Agent 자동 분석·DB 저장 (#104)
```

## 실행: 터미널 두 개

저장소 루트에서 잠금 파일 기준으로 설치한다.

```powershell
uv sync --locked --no-install-project
```

터미널 1: 서버를 켜둔다. 한 worker로 실행한다.

```powershell
uv run --no-sync uvicorn --app-dir src weeing_weeing.api.app:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 65536 --ws-max-queue 4
```

터미널 2: 기존 v4 CSV를 0.5초마다 전송한다.

```powershell
uv run --no-sync python scripts/send_csv_websocket.py --context MINIMAL
```

Unreal 패키지를 사용할 때는 CSV 송신기 대신 패키지를 실행한다. 서버 터미널에는
기본 INFO 로그 수준에서 `[센서 연결]`, `[센서 처리 #0001]`, `[센서 연결 종료]`가 표시된다.
`data=` 뒤에는 검증·탐지·저장에 성공한 전체 15필드 JSON이 출력된다. `processed_at`은
서버 처리 시각(UTC)이며 JSON의 timestamp는 송신 측 센서 시각이다. 처리 번호는 연결별
성공 메시지 수이며 멱등 재수신도 포함한다. 저장 실패한 메시지에는 성공 로그를 남기지 않는다.
검증 거부 시 원본·미검증 ID를 출력하지 않고 `[센서 거부] code=invalid_telemetry`만 남긴다.
Error 최초 진입은 별도 로그로 표시하고 D05의 매 행 사건 갱신은 출력하지 않는다.
`--log-level warning`으로 실행하면 센서 INFO 로그를 숨길 수 있다. 이미 실행 중인 서버에는
소스 변경이 자동 반영되지 않으므로 사용자가 적절한 시점에 재시작해야 한다.

빠르게 끝까지 검증하려면:

```powershell
uv run --no-sync python scripts/send_csv_websocket.py --context MINIMAL --interval 0
```

`--csv`, `--url`, `--interval`(기본 0.5초), `--timeout`(기본 10초)을 지원한다.
첫 메시지는 즉시 보내고 다음 전송은 monotonic 시계로 간격을 맞춘다. 한 행을 보낸 뒤
서버 처리 응답을 기다리므로 처리 지연 시 자연스럽게 감속하며 행을 버리거나 큐를 쌓지 않는다.
서버 오류·응답 시간 초과·연결 종료 시 중단하고 자동 재접속/재전송하지 않는다.
마지막 ACK를 못 받았더라도 서버에는 저장됐을 수 있으므로 같은 실행으로 무작정 재전송하지 않는다.

CSV의 record_id·timestamp·값은 바꾸지 않는다. 1초 간격 CSV를 0.5초마다 보내는 것은
실제 0.5초 집계 데이터가 아니다. M04의 1초/21표본 조건 등은 그대로다.

송신기 화면에는 행별 처리 확인, RPM·온도·입출구 센서, 사건의 신규/등급/상태 변화,
Error 최초 진입이 표시된다. 사건의 같은 등급/상태 반복 갱신은 화면에서 생략한다.
이력에는 모든 기존 사건 변화가 저장된다. `Error 진입`은 분석 대상을 확인했다는 뜻이며
자동 분석을 끈 기본 모드에서는 Agent를 호출하지 않는다. #104를 켰으면 ACK의
`analysis_jobs`에 등록된 작업 ID·상태를 함께 표시한다([자동 분석](AUTO_ANALYSIS.md)).

## Unreal 연결 규격

주소 기본값은 `ws://localhost:8000/ws/telemetry`다. 한 메시지에 전체 15필드 JSON 객체를
텍스트 또는 UTF-8 bytes로 보낸다. 센서값만 보내며 운전 문맥 필드를 추가하지 않는다.
JSON 고유 타입·시간대 있는 시각·버전·빈 식별자·중복 키·유한 수치·64KiB 제한은
기존 [JSON 입력 규칙](JSON_INPUT.md)을 따른다. 서버에서도 원본을 파서로 전달한다.

접속 직후 서버가 `status=connected` 메시지로 run_id·run_path·context_preset을 보낸다.
그 뒤 센서 메시지마다 아래 중 하나를 응답한다.

| status | 의미 |
|---|---|
| processed | 해당 행의 탐지·저장 성공. record_id, timestamp, incidents, error_entries 반환 |
| rejected | 형식 오류/다른 설비 입력은 invalid_telemetry. 다음 유효 입력 가능 |
| failed | 탐지·저장 실패. processing_failed 응답 후 1011로 종료. 같은 탐지기 재사용 금지 |

`agent_status`는 기본 `not_connected`, 자동 분석을 켰으면 `connected`, DB 저장 실패면
`storage_failed`다. 탐지 이력 저장과 DB 저장을 구분하려면 `db_status`도 확인한다.
`error_entries`에는 회복/종결이 아닌 최초 Error
사건 또는 Warning에서 Error로 상승한 사건의 Incident 스냅샷이 한 번만 담긴다.
코드만 추출한 메시지가 아니라 센서 근거·설비·시간·사건 ID가 포함된다.
Agent 작업 등록은 이력 처리 성공 후이며 실제 유료 분석은 별도 백그라운드 실행기에서 한다.

`rejected`는 검증기에서 거부한 메시지이며 Detector에 도달하지 않는다. 입력 거부만으로
새 품질 사건을 만들지는 않는다. 시간 공백·연속성 정책은 기존 Detector 정책을 유지한다.
동일한 직전 레코드 재수신은 기존 저장기의 멱등 처리로 사건을 중복 생성하지 않는다.
다른 값으로 같은 ID 재사용, 시간 역행, 저장 상한 도달은 처리 실패로 종료된다.

## 운전 문맥과 실행 수명

기본 `context=NONE`은 운전 문맥을 제공하지 않는다. 따라서 D05가 발생할 수 있다.
테스트 송신기의 `--context` 또는 URL 쿼리로 명시적으로 아래 DEMO 가정을 선택할 수 있다.

- RUN_ONLY: run_cmd=True
- MINIMAL: RUN_ONLY + events_reliable=True, downstream_ready=True,
  첫 행 두 센서가 false일 때만 tracking_reset=True. 이후 false

이들은 운영에서 확인된 사실이 아니다. 실제 Unreal 운전 문맥 전달은 별도 작업이다.
고정 속도·동일 하중·진동 비교 가능·승인 기준을 임의 제공하지 않는다.

### 로컬 RPM 시나리오 시험: SIM_RPM

M02/M03의 그래프·사건·알림 연결을 시험할 때만 별도 `context=SIM_RPM`을 사용한다.
`RUN_ONLY`와 `MINIMAL`의 의미는 바꾸지 않는다. 이 모드는 `run_cmd=True`,
`fixed_speed=True`, 첫 유효 센서 표본을 `run_started_at`으로 명시적으로 가정한다.
첫 3초는 기동 유예이며, 재접속하면 기동 시각도 다시 시작한다.
동일 하중·진동 비교 가능·원천 이벤트 신뢰성·승인 기준은 제공하지 않는다.
따라서 다른 룰의 Unknown과 D04/D05는 남을 수 있다. 실제 PLC 문맥 전달이나
ML 감지를 검증한 것으로 해석하지 않는다. 웹과 실행 manifest에도 시험 가정을 표시한다.

허용 조건은 아래 모두 충족해야 한다.

- 서버 프로세스에 `TELEMETRY_SIMULATION_RPM_ENABLED=true`를 명시
- 송신 클라이언트 주소와 대상 호스트 모두 loopback
- 송신 인증 모드 꺼짐, 송신 토큰 해시 미설정, `ANALYSIS_AUTO_ENABLED=false`

기본 설정은 false이며 운영 인증 서버에서는 거부한다. 시험 서버는 별도 시험 DB를
사용하고 `127.0.0.1`에만 바인딩한다. 실제 `.env`나 운영 설정을 바꿔 실행하지 않는다.
서버 준비 후 노트북 Unreal을 닫고 Python 저장소에서 실행한다. AWS 토큰은 필요 없다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\LaunchLocalRpmTest.ps1 -Project 'C:\Unreal_Projects\Weeing_Weeing_UE\Weeing_Weeing_UE.uproject'
```

설치 경로가 다르면 `-Executable`로 지정한다. Unreal 소스 수정·재빌드는 필요 없다.
M03을 선택하고 F5로 시작하면 1035 rpm 구간에서 3초 지속 후 Warning,
1045 rpm 구간에서 3초 지속 후 같은 사건이 Error로 승격된다. 약 55초 뒤
정상 범위로 돌아오고 정상 10초 지속 후 같은 사건이 RECOVERED가 되어야 한다.
상단 진행 알림 해제와 DB 이력도 확인한다. F7은 시나리오만 해제하며 서버 회복은
별도 지속 조건을 충족해야 한다. 자동 AI 분석은 실행하지 않는다.

초기 지원은 단일 프로세스·동시에 하나의 생산자 연결·한 연결당 하나의 공정/설비다.
다른 연결은 producer_busy 응답 후 1013 종료한다. 새 접속마다 새 탐지기·고유 이력 실행을
만든다. 재접속은 이전 후보/추적/사건 상태를 복원하지 않으며 연속 운전이라고 해석하면 안 된다.
동기식 저장 작업은 스레드로 넘겨 이벤트 루프를 막지 않되 한 연결 안에서는 순차 실행한다.

기본 이력 위치는 outputs/incident_history/run-… 이며 TELEMETRY_HISTORY_DIR로 변경한다.
운전 문맥 가정과 입력 경로는 실행 manifest에 보존된다. 정상 연결 종료 시 실행을 닫지만
미회복 사건을 회복시키지는 않는다. processed는 해당 행 저장 성공이고, 연결 종료 후
manifest 정리까지 확인한 최종 무결성 검증을 대신하지 않는다. 재조회에는 HistoryReader.validate()를 쓴다.

LAN 시연은 서버를 --host 0.0.0.0으로 실행하고 송신기의 --url에 서버 IP를 지정한다.
운영은 Caddy의 TLS와 송신 전용 Bearer 인증을 사용한다. 로컬은 기본 인증 끔으로 기존
시연을 유지한다. 설정·읽기 전용 조회·개인 모니터는 [AWS_TELEMETRY](AWS_TELEMETRY.md)를 따른다.
유효 입력 15초 무응답 시 연결을 닫으며, 다중 worker 상태 공유·PLC 보호 정지용 3초 watchdog은 구현하지 않았다.
실제 Agent/RAG 자동 연결은 [AUTO_ANALYSIS](AUTO_ANALYSIS.md)의 명시적 설정으로 켠다.
인증 없는 기본 로컬 모드를 외부에 공개하지 않는다.

## 자동 검증

```powershell
uv run --no-sync pytest tests/api/test_websocket_telemetry.py tests/scripts/test_send_csv_websocket.py
```

형식 오류 후 유효 입력, bytes, 중복 키, 크기 제한, 단일 연결, 설비 분리,
탐지·저장 실패와 재사용 금지, 0.5초 Error 확정, Error 진입 중복 억제·회복,
v4 300행 이력, 실제 TCP/Uvicorn 송신과 실패 ACK 후 중단을 검증한다.
