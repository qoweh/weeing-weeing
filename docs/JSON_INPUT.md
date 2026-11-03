# 공통 JSON 입력과 CSV 재생

입력 흐름은 `CsvJsonSource → JSON 메시지 → JsonTelemetryInput → TelemetryRecord
→ 주입한 handler → HistoryDetector.process`다. 실행 중 같은 Detector 인스턴스를
유지하며 한 메시지당 한 번 호출한다. ingest는 탐지·PLC·Agent·DB 구현을 import하지
않는다. 기존 스냅샷 데모 `demo_incident_json.py`와 contracts는 변경하지 않는다.

## 공개 API

`weeing_weeing.ingest.interface`에서 다음을 import한다.

```python
from weeing_weeing.ingest.interface import (
    CsvJsonSource,
    JsonTelemetryInput,
    parse_telemetry_json,
    replay_json,
    TelemetryInputError,
    CsvTelemetryError,
)

receiver = JsonTelemetryInput(detector.process, max_message_bytes=64 * 1024)
changes = receiver.receive(message, plc_context=verified_context)
record = parse_telemetry_json(message)  # 검증만 수행
count = replay_json(CsvJsonSource(csv_path), receiver.receive, interval_s=0.5)
```

한 메시지는 전체 15필드 JSON 객체다. 전류·온도 결측도 명시적인 null이어야 한다.
문자열 또는 UTF-8 bytes를 받으며 기본 상한은 UTF-8 인코딩 기준 64KiB다.
숫자·불리언 문자열 자동 변환, bool 센서 수치, 빈 식별자, 시간대 없는 시각,
미지원 버전, 중복 키, 누락·추가 필드, 복수 객체·배열, 비유한 수치·overflow를
거부한다. 센서 임계값 초과는 허용하며 판정은 Detector가 한다.
입력 오류는 원본 값을 포함하지 않는 `TelemetryInputError(ValueError)`이고 handler를
호출하지 않는다. 이후 유효 메시지는 처리할 수 있다. handler 예외는 원형 그대로
전파하고 재시도하지 않는다. HistoryDetector가 실패하면 기존 재사용 금지 정책을 따른다.

CSV는 UTF-8/BOM을 지원하고 헤더 순서는 자유지만 정확히 같은 15필드가 필요하다.
CSV 불리언은 대소문자 무관 true/false, 수치는 float, 빈 선택 센서는 null로 변환한다.
생성 JSON은 공통 파서로 검증한다. 잘못된 헤더·행·인코딩은 물리 줄 번호가 있는
`CsvTelemetryError`로 중단한다. 한 행씩 읽으며 전체 파일이나 이력을 적재하지 않는다.

재생은 첫 메시지를 즉시 전달하고 직전 전달 시작부터 monotonic 간격을 맞춘다.
처리가 간격보다 느리면 끝난 뒤 다음 행을 전달하며 놓친 슬롯을 따라잡는 연속 전송을
예약하지 않는다. 행을 버리거나 백그라운드 큐를 만들지 않는다. 중간 예외는 즉시
중단한다. 기본 간격은 0.5초, 0은 대기 없음이며 음수·비유한 값은 거부한다.
`monotonic=`과 `sleep=` 주입으로 대기 없이 테스트할 수 있다.
단일 프로세스·순차 호출만 지원한다.

## 사건 이력 데모

터미널에서 데이터가 들어오는 과정을 보려면 `--live`를 추가한다.

```powershell
uv run --no-sync python scripts/demo_incident_history.py --csv data/telemetry/battery_tray_transfer_5min_warning_error_v4.csv --context MINIMAL --codes BTT2-M10 --interval 0.5 --live
```

이 명령은 온도 룰 M10만 활성화해 흐름을 관찰한다. `--codes BTT2-M10`을 빼면
전체 룰이 실행된다. v4 전체 300행은 0.5초 간격 기준 약 150초가 걸린다.
더 빠르게 보려면 `--interval 0.1`로 실행한다. 센서 timestamp는 어느 속도에서도 유지한다.

매 행마다 PC 수신 시각·재생 경과시간·원본 센서 timestamp·record_id와 전체 센서값을
출력하고, 탐지와 저장이 끝나면 실제 사건의 신규·갱신·등급 변경·회복을 표시한다.
D05는 동일 사건의 부족 항목·등급·상태가 같으면 반복 출력하지 않는다. 부족 항목이
바뀌면 다시 표시하고 회복 시 해소를 알린다. 새로운 D05 사건은 다시 표시한다.
평가기의 D05 근거에 포함된 룰 코드를 RPM·전류·저온·진동·상대 진동으로 묶어
확인이 필요한 조건을 안내한다. 각 줄은 해당 룰의 요구 조건이며 나열한 조건이
모두 누락됐다는 뜻은 아니다. 문맥을 임의로 채우거나 탐지·이력 저장을 생략하지 않는다.
null 센서도 null로 표시한다. 사건 변화가 없다는 표시는 정상 판정을 뜻하지 않는다.
확정 전 후보 상태를 별도로 추정하지 않으며, 신규 사건 발생 시 Detector가 반환한
후보 시작·확정 시각을 표시한다. 출력은 즉시 flush한다.

실시간 로그는 stderr, 기존 최종 JSON 요약은 stdout에 출력한다. 따라서
`--live` 없이 기존 동작을 유지하거나 `1> summary.json`으로 요약만 저장하면서
터미널에서 실시간 로그를 볼 수 있다. Ctrl+C로 중간에 종료하면 성공 완료 검증을
표시하지 않으며, 부분 실행은 기존 이력 저장기의 failed 상태로 남는다.

```powershell
uv run --no-sync python scripts/demo_incident_history.py --csv data/telemetry/battery_tray_transfer_5min_warning_error_v4.csv --context MINIMAL --interval 0 --output outputs/incident_history
```

`--codes`, `--buffer-seconds`, `--buffer-rows`도 유지한다. 기본 `--interval`은 0.5다.
MINIMAL은 run_cmd, events_reliable, downstream_ready를 True로 가정하고 첫 행의
입출구 센서가 모두 False일 때만 tracking_reset=True다. 이후는 False다.
고정 속도·동일 하중·진동 비교 가능·승인 기준은 제공하지 않는다. RUN_ONLY는
run_cmd=True만 가정한다. 두 문맥 모두 운영 사실이 아닌 시뮬레이션 가정이다.

실행 manifest의 source에 CSV 경로·SHA-256·JSON 입력 경로·간격·문맥 가정을
보존한다. 종료 후 HistoryReader.validate()로 검증하고 실제 입력 행 수, 사건별
이벤트·센서 행 수, 파일 바이트 수와 고유 실행 경로를 출력한다.

## 0.5초 송신과 집계 의미의 제한

현재 TelemetryRecord 설명은 1초 집계 구간이며 실제 v4 CSV는 1초 timestamp 간격이다.
이를 0.5초마다 전송해도 record_id·timestamp·센서값을 바꾸지 않는다. 따라서 실제
0.5초 집계 데이터가 아니다. 공통 입력은 0.5초 timestamp를 허용하고 수치 룰은
센서 timestamp 경과시간으로 확정된다. PC 재생 시계는 탐지 시각으로 사용하지 않는다.

전체 룰이 0.5초 데이터에 대응 완료된 것은 아니다. 특히 builtin_rules의 M04는
20초 창에 정확히 21표본, 인접 간격 1초를 요구한다. 0.5초 입력은 이 조건을
충족하지 못해 Unknown이 된다. 광전 룰의 5개 이벤트/전송 관측, 추세 룰의 표본 수·
창 경계와 버퍼 행 상한도 더 높은 송신 빈도에서 별도로 검토해야 한다.
기존 2초 초과 공백 정책·지속시간·회복 정책은 유지한다. 0.5초 집계의 의미 정의와
모든 룰 대응, WebSocket/Unreal·PLC 제어·Agent/RAG·DB 연결은 별도 작업이다.

## 검증

`uv run --no-sync pytest tests/ingest`로 엄격한 입력 거부, 단일 호출, CSV 왕복,
fake clock 재생·실패 중단, 0.5초 수치 룰 확정·직접 경로 동등성·후보/회복 저장,
기록 실패 후 재사용 금지를 검증한다. 실제 v4가 있으면 원본 CSV 직접 입력과
CSV→JSON 경로를 매 행 비교하고 이력도 재검증한다. v4가 없으면 해당 테스트는 skip한다.

2026-10-26 로컬 v4 검증: 300행, 사건 3개(M08/M10/D05), 변화 스냅샷 372개.
M10 후보 81초, Warning 91초, Error 109초, 마지막 이상 136초, 회복 147초,
센서 67행(81~147초), 회복 대기 10행(137~146초)으로 참고값과 일치했다.
D05는 열린 상태로 남고 문맥을 추가해 없애지 않았다.
