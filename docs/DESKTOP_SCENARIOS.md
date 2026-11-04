# 센서·사건 저장 전용 시험

Unreal 고장 시나리오를 시험할 때 Claude를 호출하지 않고 센서·사건을 DB에 저장한다.
기존 15필드 JSON·0.5초 송신·같은 record_id ACK·생략/무재전송 정책은 유지한다.
M04/M19 새 문맥·정상 기준 승인과 ML 실험은 이 기능에 포함되지 않는다.

## 설정과 실행

기존 DB를 초기화하지 말고 새 시험 DB를 준비한 뒤 해당 DATABASE_URL을 사용한다.
원본 DB 백업·복원과 서버 실행은 로컬 환경을 확인한 후 사용자가 진행한다.
비밀값을 편집기나 채팅에 입력하면 IDE 자동 문맥에 포함될 수 있으므로 실제 키를
열거나 출력하지 않는다. 저장 전용에는 Claude 키나 RAG 모델·색인이 필요 없다.

다음 명령은 사용자가 PowerShell에서 실행하는 예시다. 지정한 환경값이 프로세스의
모드를 결정한다. 실제 .env를 로드하지 않는다.

```powershell
cd C:\Weeing-Weeing\weeing-weeing
$env:TELEMETRY_DB_ENABLED = 'true'
$env:ANALYSIS_AUTO_ENABLED = 'false'
$env:PYTHONUTF8 = '1'
# DATABASE_URL은 본인이 준비한 새 시험 DB를 가리키도록 먼저 설정한다.
uv run --no-sync --no-env-file uvicorn --app-dir src weeing_weeing.api.app:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 65536 --ws-max-queue 4 --log-level info
```

운영 중인 8000 서버가 있으면 중복 실행하지 않는다. 소스·환경값 변경 후 기존 인스턴스를
임의로 재시작하지 말고 시험할 인스턴스를 확인한다. 단일 worker/replica만 지원한다.
기존 Unreal 연결 예시는 `ws://127.0.0.1:8000/ws/telemetry?context=RUN_ONLY`이며,
RUN_ONLY는 시뮬레이션 가정이다. SIM_DEMO 문맥은 이 기능에서 추가하지 않는다.

## 터미널과 ACK 확인

저장 전용으로 시작하면 다음 로그가 나온다.

```text
[분석 비활성] ANALYSIS_AUTO_ENABLED=true로 자동 호출 활성화(비용 발생)
[DB 저장 활성] 센서·사건만 저장; 분석 작업 등록·호출 없음
```

첫 번째 메시지는 현재 비활성 상태와 활성화 방법의 안내다. 현재 유료 호출을 켰다는 뜻이 아니다.
실제 검증 통과 프레임에는 다음 상태가 포함된다.

```json
{"status":"processed","agent_status":"not_connected","db_status":"saved","analysis_jobs":[]}
```

이는 전체 ACK 중 상태 필드 발췌다. 수신 성공만으로 DB 저장을 판단하지 말고
db_status=saved를 별도로 확인한다. Error 진입 로그의 agent는 `미연결(DB 저장 전용)`이며,
분석 등록·시작 로그는 생성되지 않아야 한다. DB 실패는 failed/storage_failed로 보고하고
재전송하거나 유료 대기 작업으로 전환하지 않는다.

## 자동 회귀 — 사용자 DB·실제 Claude 없이 확인

```powershell
$env:ANALYSIS_AUTO_ENABLED = 'false'
$env:TELEMETRY_DB_ENABLED = 'false'
uv run --no-sync --no-env-file pytest tests/api/test_analysis.py -k storage_only -vv
```

자동 검사는 임시 SQLite·테스트용 WebSocket과 가짜 객체만 사용한다. P03와 M10 각각
Error→RECOVERED, DB 저장, 분석 0건, 기존 대기 작업 미실행, 기존 분석 조회 허용과
재요청 차단을 확인한다.
실제 Unreal 패키지나 사용자 서버의 시험 완료를 의미하지 않는다.

## 실제 시나리오 확인 순서

1. 정상 운전 송신: 15필드·같은 ID ACK·시간 순서·db_status=saved 확인.
2. P03 시험: 주입 시작/해제·예상 Error·RECOVERED와 같은 incident_id 확인.
3. M10 시험: 실제 주입 온도·지속시간·기준 초과·정상 복귀 후 회복 확인.
4. 매 실행 전후 센서/사건 건수와 analysis_job/analysis 건수를 대조한다. 저장 전용에서는
   분석 작업·결과가 증가하지 않아야 한다. D04/D05 등 동반 코드는 숨기지 않고 기록한다.
5. HMI에서 사건을 새 보고서에 연결해 임시 저장·재조회한다. 분석이 없는 사건의 AI
   영역은 연결 대기로 남는 것이 정상이다. 실제 조치·확정 원인·결재를 자동 작성하지 않는다.

수신·로컬 이력·DB 저장·AI 완료·센서 회복·사람 승인 종결은 각각 다른 상태다.
저장된 사건 한 건만 나중에 분석하려면 `scripts/analyze_incident.py`의
`--ask-key --result-out 새파일.json --save-db`를 사용한다. 실제 유료 호출은 사용자가
본인 터미널에서 실행하며 자동 분석 서버를 켤 필요는 없다. 결과와 정확한 입력 스냅샷은
함께 저장하고 현재 사건 상태는 바꾸지 않는다. 준비·옵션은 [스크립트 안내](../scripts/README.md)를
따른다. ML 이식·테스트·실험은 팀 회의 이후로 보류한다.
