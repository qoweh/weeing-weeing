# 사건 이력 파일 저장 v1

`Incident`는 최신 요약이다. 선택적으로 켜는 `detector.interface.HistoryDetector`는
새 `RuleDetector` 하나를 소유하며 각 입력을 `process_frame()`에서 **한 번만** 평가한다.
평가기의 순간 판정·후보/회복 타이머 상태와 Manager의 변경 결과를 함께 기록한다.
임계값·지속시간·회복 조건을 저장기가 다시 계산하지 않는다.
기존 `RuleDetector.process()`와 `Incident` 계약, 스냅샷 JSON 데모는 유지한다.
Agent/RAG/DB/HMI를 호출하거나 구현하지 않는다.

## 실행

저장소 루트에서 실행한다. 의존성 추가는 없다. 설치가 필요하면
`uv sync --locked --no-install-project`를 쓴다.

```powershell
uv run --no-sync python scripts/demo_incident_history.py
uv run --no-sync python scripts/demo_incident_history.py --csv data/telemetry/battery_tray_transfer_5min_warning_error_v4.csv --context MINIMAL --output outputs/incident_history
uv run --no-sync python scripts/demo_incident_history.py --codes BTT2-M10 --buffer-seconds 120 --buffer-rows 2048
```

CSV가 실제 존재해야 한다. v4라는 이름의 합성 대체 파일을 생성하지 않는다.
데모는 실행 경로·사건별 행 수·이벤트 수·센서 파일 바이트 수·실행 전체 바이트 수를
**생성된 파일에서 측정**해 출력한다. 원본 CSV 경로와 SHA-256도 manifest에 보존한다.

`RUN_ONLY`는 `run_cmd=True`만 가정한다. `MINIMAL`은 시뮬레이션 가정으로
`run_cmd=True`, `events_reliable=True`, `downstream_ready=True`를 제공하고,
첫 행의 입출구 센서가 모두 False일 때만 첫 행 `tracking_reset=True`를 준다.
그 이후는 False다. 고정 속도·동일 하중·진동 비교 가능·승인 진동 기준은 제공하지 않는다.
D05가 남아도 문맥을 만들어 제거하지 않는다. 운영에서 확인된 PLC 사실이 아니다.
입력별 실제 문맥은 센서 행의 별도 annotation에 보존한다.

## 저장과 재조회

기본 경로는 `outputs/incident_history/run-<UUID>/INC-<UUID>/`다.
새 실행은 항상 고유 디렉터리를 만든다. 재시작 시 기존 디렉터리를 이어 쓰지 않는다.

| 파일 | 내용 |
|---|---|
| 실행 루트 `manifest.json` | history schema_version, source, 룰 버전·정책·수치 임계값·구현 해시, 버퍼 설정, 입력 수, 완료/실패 상태, 미완료 입력 |
| `incident.json` | 기존 Incident 형식의 최신 스냅샷 |
| `events.jsonl` | confirmed/updated/escalated/recovered, 실제 입력 timestamp·record_id, 당시 Incident |
| `telemetry.jsonl` | incident_id, 원본 15필드 `record`, 판정·타이머·문맥을 구분한 `annotation` |
| `metadata.json` | 요청/실제 저장 구간, 후보 앞부분 누락, 시간 공백 수, 종료 사유, 파일별 행 수·바이트 수·SHA-256 |

각 부가 파일/JSONL 행에는 Incident의 schema와 별개인 history `schema_version=1.0.0`을
둔다. `record`는 CSV 문자열 자체가 아니라 검증된 `TelemetryRecord`의 전체 필드다.
빈 선택 센서값은 null이며 0으로 채우지 않는다. timestamp의 시간대를 유지한다.
비유한 센서값은 JSON 표준을 지키면서 `{"$float":"nan"}` / `inf` / `-inf`로
보존하고 Reader에서 float로 복원한다. 이 표기는 history 전용이다.

```python
from pathlib import Path
from weeing_weeing.detector.interface import HistoryDetector, HistoryReader

with HistoryDetector(
    Path("outputs/incident_history"), source={"kind": "stream"}
) as sink:
    for record, verified_context in input_stream:
        changes = sink.process(record, verified_context)
        # 이번 범위에서는 Agent를 호출하지 않는다.

reader = HistoryReader(sink.run_path)
reader.validate()  # 실행 완료, 파싱/순서, 체크포인트 크기·행 수·해시 확인
for incident_id in reader.list_incidents():
    latest = reader.incident(incident_id)
    metadata = reader.metadata(incident_id)
    for event in reader.events(incident_id):
        pass
    for entry in reader.telemetry(incident_id):  # 전체 센서 파일을 적재하지 않음
        record_fields = entry["record"]
```

모듈 외부에서는 위 `interface.py`만 사용한다. Reader 생성만으로 무결성이 보장되는
것은 아니므로 완전한 실행으로 이용하기 전에 `validate()`한다. 미완료 실행도 명시적으로
JSONL 순회를 시도할 수 있지만, 파싱 불가능한 마지막 행과 순서 오류를 건너뛰지 않는다.
체크섬은 우발 손상/부분 기록 검출용이며 악의적인 파일·해시 동시 변조 방어 수단은 아니다.

## 수집 경계와 시각화 정보

- 확정 전에는 공정·설비별 유한 버퍼만 둔다. 확정 시 `first_detected_at` 이상인
  버퍼 행을 복사한다. 미확정 후보와 사건 없는 정상 운전에는 사건 디렉터리를 만들지 않는다.
- 확정 이후 Manager의 변경이 없는 입력도 수집한다. recover의 실제 정상 행을 포함한 뒤
  수집을 끝낸다. `active_incidents()`의 RECOVERED 포함 여부로 수집 여부를 결정하지 않는다.
- 재발은 새 ID다. 동시 사건은 센서 행을 각각 복제한다. 파일 용량은 사건 중첩 수에
  비례해 증가한다. 다른 공정·설비 행은 섞지 않는다.
- `annotation.assessment`는 순간 판정이다. `phase`는 평가기 상태에서 가져온
  candidate/ongoing/recovery_wait/recovered/normal/unknown/suppressed이며,
  `collection_phase`는 확정 전 소급 저장 범위를 candidate로 표시한다.
  과거 시작 시각을 주는 이벤트 룰에서는 이 소급 범위에 당시 normal/unknown 행도 있을 수 있다.
  원래 `phase`와 판정·사유는 그대로 남으므로 이를 정상 회복으로 재해석하면 안 된다.
- Error 사건에서 순간 판정이 Warning이어도 Incident를 낮추지 않는다.
  회복 스냅샷의 evidence·last_detected_at은 마지막 이상 상태이고, recovered_at과 별개다.
- `input_delta_seconds`는 직전 수신 행과의 시간차다. 1초 초과는 sampling discontinuity로
  센다. `gap_seconds`는 기존 평가기가 타이머를 끊는 **2초 초과** 공백만 표시한다.
  공백 뒤 실제 Normal 판정은 새 recovery_wait를 시작할 수 있지만 수신하지 않은 행을
  보간하거나 복원하지 않는다. Unknown/Suppressed는 회복 대기로 바꾸지 않는다.

## 메모리와 완전성

기본 버퍼는 설비별 입력 시각 기준 120초, 최대 2048행이다. 수치 룰은 최대 10초 후보,
M04는 20초 관측 창과 3초 확정 지연 등으로 과거 문맥을 사용한다. 120초는 이런 짧은
구간을 위한 기본값이며 모든 룰의 후보 보존 보장이 아니다. P01/P06처럼 오래된 대기
트레이를 시작으로 삼는 룰과 사용자 시간 정책은 더 긴 과거를 요구할 수 있다.
`HistoryConfig(buffer_seconds=..., buffer_rows=...)`로 두 상한을 조정한다.

`candidate_prefix_missing`, `requested_start`, `actual_start`로 앞부분 누락을 표시한다.
행이 없어 원래 시작 시각을 복구할 수 없는 경우에도 가짜 행을 만들지 않는다.
정상 행도 confirm 전 유한 버퍼에는 들어가지만 파일에 계속 적재하지 않는다.
센서 이력 전체를 메모리에 쌓지 않는다. 버퍼 행에는 판정·문맥도 들어가므로 크기가 크다.
최대 설비 64개, 실행당 고유 입력 최대 100,000개로 설비 상태와 ID 중복 검사 메모리도
제한한다. 상한 도달 시 조용히 이전 ID를 잊지 않고 실패 중단한다. 설정으로 조절하거나
새 실행으로 나눈다. 새 실행은 탐지 연속성이 보장되지 않는다.

직전 동일 설비의 같은 입력(문맥·외부 평가 포함) 재수신은 무시한다. 이미 사용한 ID의
다른 값, 과거 ID 재사용, 시간 역행/동일 timestamp는 실패 중단한다. ID 범위는 기존
평가기처럼 공정·설비별이다. 과거 행을 뒤늦게 재수신해도 정렬하거나 덮어쓰지 않는다.

## 실패·종료·보관 제한

지원 범위는 **단일 프로세스, 순차 호출**이다. 공유 디렉터리 동시 쓰기나 Reader와 Writer의
동시 무결성 검사는 지원하지 않는다. 각 JSONL append 후 flush/fsync한다.
최신 JSON 파일은 임시 파일을 fsync한 뒤 replace한다. Windows의 일시적 파일 잠금에
한해 replace만 최대 6회 시도한다. 입력 평가나 JSONL append를 재실행하는 재시도가 아니다.

여러 파일은 하나의 트랜잭션이 아니다. 매 입력 전에 manifest에 pending 입력을
기록하고, 해당 행의 파일·메타데이터 저장이 끝나야 지운다. 갑작스러운 종료 시 running,
pending, 남은 tmp, 파일 크기·행 수·해시 불일치로 미완료/부분 기록을 판별한다.
디스크 장애로 실패 표시 자체를 쓰지 못해도 이전 running/pending 기록이 남는다.
전원 차단에 대한 디렉터리 엔트리의 하드웨어 수준 내구성을 보장하지는 않는다.

탐지 상태가 이미 진행된 뒤 저장이 실패할 수 있다. 모든 처리 오류 후 인스턴스를
실패 상태로 만들고 **동일 입력 재처리와 후속 입력을 거부**한다. 원인 해결 후 새 실행에서
소스를 처음부터 재생해야 한다. Detector/Manager 메모리 복원과 실행 이어 쓰기는 제외한다.

정상 입력 종료도 회복이 아니다. `close()`/with 종료는 최신 Incident 상태를 유지한 채
미회복 사건의 collection_end_reason만 `input_end`로 기록한다. manifest completed는
입력 처리가 정상 종료되었다는 뜻이며 모든 사건이 RECOVERED/CLOSED라는 뜻이 아니다.
예외 종료는 failed/completed=false다. 프로세스 강제 종료 시 running이 남는다.

`outputs/`는 Git 제외 대상이다. 결과는 해당 PC 디스크에만 저장되고 자동 백업·PC 간
동기화·보관 기간·자동 삭제 기능은 없다. 삭제와 백업은 사용자가 별도 관리한다.
