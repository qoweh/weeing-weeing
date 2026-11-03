# Unreal AWS 센서 연결과 개인 확인

## 작업 범위

기존 수신·Detector·DB 저장 흐름을 유지하고 인증, 최신 상태 조회, 개인용 CLI를 추가한다.
기존 프론트엔드·대시보드·준비 화면·헤더·보고서 UI는 변경하지 않는다.
팀원이 구현할 실시간 화면은 아래 조회 API를 선택적으로 연결할 수 있다.
이 변경은 배포를 의미하지 않는다. 운영 적용·유료 분석은 별도 승인 후 진행한다.

```text
데스크탑 또는 노트북 Unreal (동시에 하나)
  → WSS :443 /api/ws/telemetry → Caddy → FastAPI /ws/telemetry
  → 기존 15필드 검증 → 기존 HistoryDetector → 기존 선택적 DB 저장
  → 제한된 메모리 최신 상태 → 인증된 개인 CLI / 팀원 화면
```

Unreal WSS 주소는 `wss://telemetry.<EC2_IP>.sslip.io/api/ws/telemetry`다.
Unreal의 IP 인증서 이름 검사에서 확인된 Hostname mismatch를 DNS 인증서로 해결한다.
TLS 검증을 끄지 않는다. 기존 IP 웹 주소와 Python 개인 모니터의 기본 주소는 유지한다.

## 송신 인증과 기존 기능

- 운영 compose는 `TELEMETRY_AUTH_REQUIRED=true`를 강제한다. SHA-256 설정이 없거나
  잘못되면 WebSocket accept·생산자 잠금·이력 생성 전에 거부한다.
- 서버에는 `TELEMETRY_PRODUCER_TOKEN_SHA256`만 설정하고, 송신기는 원본 전용 토큰을
  `Authorization: Bearer` 헤더에 전달한다. 웹 로그인 세션과 별개다.
- 로컬은 기본 인증 끔으로 기존 CSV 송신기·Unreal·독립 시험을 유지한다.
  로컬에서도 해시를 설정하면 인증한다. 토큰을 URL·로그·명령줄에 넣지 않는다.
- `TELEMETRY_DB_ENABLED=true`, `ANALYSIS_AUTO_ENABLED=false`이면 DB만 저장한다.
  `processed`와 `db_status=saved`는 별도이며 실패 표본을 자동 재전송하지 않는다.
- 15초간 유효 입력이 없는 생산자는 종료하고 자리를 반납한다. 수신 연결 하나, API worker와
  replica 하나를 유지한다. 기본 이력 상한 10만 표본(2Hz 약 13시간 53분)은 그대로다.
- 재접속은 새 감지 세션이다. 이전 후보·사건 상태를 복원하거나 미회복 사건을 회복시키지 않는다.
- `RUN_ONLY`, `MINIMAL`은 시뮬레이션 가정이다. M04 표본 간격 및 M19 승인 기준 제한은 유지한다.
  실제 PLC 정지·재가동이나 사람의 승인을 새로 연결하지 않는다.

## 팀원 화면 연결용 조회 API

아래 주소는 FastAPI 기준이다. AWS 외부 주소에는 `/api`를 앞에 붙인다.
기존 `POST /auth/login`의 Bearer 로그인으로 조회한다. 송신 전용 토큰으로 조회하지 않는다.

| 경로 | 동작 |
|---|---|
| `GET /telemetry/latest` | 최신 스냅샷 한 개. 미수신도 200이며 `telemetry=null`, `stale=true` |
| `GET /telemetry/stream` | SSE `event: snapshot`, `data: {"event":"snapshot","state":{...}}` |
| `GET /incidents` | 기존 DB 사건 목록. 이전 세션의 미회복 사건도 여기에서 확인 |
| `GET /incidents/{id}/analysis` | 기존 AI 작업 상태·최종 결과 조회. 분석을 새로 요청하지 않음 |

스냅샷 필드:

| 필드 | 의미 |
|---|---|
| `epoch`, `run_id`, `sequence` | 프로세스·감지 세션·변경 순번. 새 epoch/run이면 그래프 초기화 |
| `producer_connected`, `stale`, `age_seconds` | 연결·3초 초과 지연·마지막 표본 처리 후 경과시간 |
| `received_at` | 마지막 표본의 탐지·저장 시도 후 서버 시각(UTC). 센서 시각과 구분 |
| `telemetry` | 기존 전체 15필드 객체 또는 null. 입력 계약은 변경하지 않음 |
| `context_preset` | NONE / RUN_ONLY / MINIMAL |
| `db_status`, `agent_status` | 마지막 표본의 DB·분석 연결 상태. AI 완료를 뜻하지 않음 |
| `incidents` | 현재 세션의 최근 최대 100건 요약. ID·코드·설비·최초 감지·등급·상태 |

SSE는 0.5초마다 최신 상태를 보내며 브라우저별 이벤트 큐는 만들지 않는다. 느린 구독자는
중간 상태를 건너뛸 수 있다. 모든 표본의 영속 저장·사건 목록은 기존 DB가 기준이다.
토큰은 URL에 넣지 않고 Bearer 헤더를 지원하는 fetch로 구독한다.
연결 중 로그인 세션은 10초마다 재검증하며, 만료·로그아웃·계정 비활성화·DB 장애 시
`event: error`의 `status_code`를 보낸 후 종료한다. 클라이언트는 401/403이면 재로그인,
그 외에는 대기시간을 늘려 재접속하고 첫 스냅샷으로 다시 동기화한다.
스냅샷은 메모리 캐시이므로 API 재시작 시 비워진다. 연결 단절·지연을 정상/0건으로 표시하지 않는다.
사건 요약은 수신 시 Detector 변화 기준이다. 사람의 ACK·보고서 처리에 따른 최신 상태는
기존 DB 사건 목록을 조회해서 갱신한다.
통신 복구는 사건 회복이나 재가동 승인이 아니다.

## 나만 확인하는 터미널 모니터

설치·실행은 README의 잠금 파일 기준 환경을 사용한다.
새 API가 로컬에서 실행 중이면 본인 PowerShell에서:

```powershell
uv run --no-sync python scripts/watch_telemetry.py --base-url http://127.0.0.1:8000
```

승인 후 새 API가 AWS에 배포되면:

```powershell
uv run --no-sync python scripts/watch_telemetry.py
```

본인 사번과 로그인 비밀번호를 터미널에서 입력한다. 비밀번호는 숨김 입력하며 파일·로그에
남기지 않는다. IDE에는 열린 파일이 자동 문맥으로 전달될 수 있으므로 비밀번호·토큰을
편집기·예시 파일·채팅에 입력하지 않는다. .gitignore·숨김은 OS 읽기 차단이 아니다.
모니터는 1초마다 조회하며 센서 10개 값·서버 처리 시각·DB 상태·최근 사건을 표시한다.
`--once`는 한 번만 조회한다. 종료는 Ctrl+C이며 자신의 모니터 로그인 세션을 로그아웃한다.
웹을 수정하거나 AI 분석·제어·보고서 작성을 요청하지 않는다. 조회 오류 시 중단하며
이전 값을 정상으로 재사용하지 않는다. HTTPS 인증서 검증을 끄거나 외부 HTTP로 로그인하지 않는다.

## 승인 후 운영 적용 순서

1. 사용자 터미널에서 비밀번호 관리 도구 등으로 32자 이상의 무작위 송신 전용 토큰을 준비한다.
   원본은 저장소·로그·채팅에 남기지 않는다. 데스크탑·노트북 담당자만 사용한다.
2. 본인 터미널에서 `uv run --no-sync python scripts/hash_telemetry_token.py`를 실행하고
   토큰을 숨김 입력한다. 출력되는 SHA-256만 서버 설정의 `TELEMETRY_PRODUCER_TOKEN_SHA256`에 등록한다.
   에이전트는 실제 토큰·.env를 읽거나 검증하지 않는다.
   Windows에서 Python 숨김 입력의 붙여넣기가 되지 않으면 비밀번호 관리 도구에서 토큰을
   복사한 뒤 본인 PowerShell에서 `.\scripts\HashTelemetryToken.ps1 -FromClipboard`를 실행한다.
   이 명령은 클립보드에서 토큰을 읽어 해시만 출력하며 파일에 원본을 저장하지 않는다.
   에이전트는 실제 클립보드를 읽지 않으며 자동 검증은 가짜 클립보드 함수로만 한다.
3. 검증된 이미지 배포 후 DB 저장 켬·자동 분석 끔·단일 worker·API healthy를 확인한다.
   인증 필수화 때문에 해시가 누락되면 송신은 거부된다. Caddy 경로 변경이나 8000 포트 공개는 불필요하다.
4. Unreal 저장소의 `Scripts/LaunchTelemetry.ps1 -Mode AWS`로 실행하고 원본 토큰을 숨김 입력한다.
   최신 패키지가 필요하다. Editor 빌드 성공만으로 기존 패키지가 갱신되지는 않는다.
5. 개인 모니터에서 수신 시각·표본 ID·`db_status=saved`와 실제 DB 저장을 확인한다.
   알려진 고장 하나를 주입·해제하고 사건 생성·회복을 별도로 확인한다.
6. 데스크탑을 종료한 뒤 노트북으로 연결해 새 세션과 과거 사건 보존을 확인한다.
   팀원 화면은 담당자의 커밋 이후 실제 API 연결 규격을 맞춰 별도로 검증한다.

## 자동 검증

```powershell
uv run --no-sync pytest tests/api/test_telemetry_live.py tests/api/test_websocket_telemetry.py tests/scripts/test_watch_telemetry.py
```

가짜 토큰·가짜 사용자·임시 SQLite만 사용한다. 실제 .env·운영 서버·유료 LLM은 사용하지 않는다.
