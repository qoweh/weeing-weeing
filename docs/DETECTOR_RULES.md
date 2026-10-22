# 공통 룰 평가와 Incident 연결

기준은 `data/parsed/BTT-RULE_v2.0.md`다. 이 구현은 DEMO이며 제어 명령을 실행하지 않는다.

## 사용

```python
from weeing_weeing.detector.interface import RuleDetector

detector = RuleDetector()  # 실행 동안 유지. 기본은 CODES의 31개 코드
changed = detector.process(record, {"run_cmd": True})
assessments = detector.last_assessments  # 룰별 후보 상태와 사유
```

`enabled_codes={"BTT2-P03", "BTT2-M08"}`로 범위를 제한할 수 있다. 반환 Incident에는
관련 센서 근거만 담는다. 원본 15컬럼 스냅샷이나 전체 시계열을 자동 누적하지 않는다.
데이터 품질의 사유는 `telemetry_quality` 근거의 observed에 담는다.

## 책임

| 파일 | 책임 |
|---|---|
| `builtin_rules.py` | 센서·이벤트·문맥으로 룰별 순간 후보와 명시적인 정상/Unknown/Suppressed 생성 |
| `rule_models.py` | 모든 코드에 공통인 `RuleAssessment`, `RulePolicy`, `RuleDecision` |
| `rule_engine.py` | 후보 지속시간, 등급 유지, 회복 확정, Manager 호출 |
| `incident_manager.py` | 확정 결과의 사건 생성·갱신·RECOVERED 기록 |

기존 `anomaly_detector.py`, `detection_models.py`, `observation.py`의 관측 전용 API는
제거했다. 호출부는 `RuleDetector.process()` 또는 룰 코드가 포함된 `RuleAssessment`를
사용한다. 기존 관측 테스트의 수치 경계·시간·중복·설비 분리 검증은 공통 엔진 테스트로
대체하며, 초기 재공을 추측하는 FIFO 동작은 재동기화가 필요한 정책으로 변경했다.

별도 룰 구현도 `process_assessments(record, assessments)`에 같은 모델을 전달한다.
이 경로는 기본 내장 평가기를 대신한다. 한 레코드에서 두 경로를 중복 호출하지 않는다.
코드·등급·근거·선택적 방향 및 사건 후보 시작 시각을 전달한다. 생략한 코드는
Unknown이다. 같은 코드의 평가를 한 입력에 중복 제공하면 오류다.

후보 시작 시각은 메타데이터다. 이를 과거로 지정해 공통 지속시간을 건너뛸 수 없다.
이벤트 자체로 확정되는 룰은 기본 지속시간이 0이며 이벤트 계산의 시작 시각을 보존한다.
외부 평가기로 정상 이벤트 횟수·점검 확인 등 회복 조건을 판단할 경우, 조건 충족 시에만
Normal을 보내야 한다. `policies={code: RulePolicy(warning_s=..., error_s=..., recovery_s=...)}`로
시간 정책을 바꿀 수 있다. 0은 즉시 확정이다.

## 내장 룰

| 룰 | 후보·확정·회복 |
|---|---|
| M02/M03, M05/M06, M11~M18 | 정의서 A/B/C 경계, 같은 방향 Warning 이상 및 Error 각각 3초 연속, A 안 10초 회복 |
| M07/M08 | A/B/C, 1초 지속, A 안 10초 회복. RUN 지령 없이도 유효 전압 평가 |
| M09/M10 | A/B/C, 10초 지속, A 안 10초 회복. 저온은 RUN 예열 600초 이후, 고온은 예열 중에도 평가 |
| M01 | RUN 기동 3초 이후 rpm <1000, 또는 기동 완료 후 rpm <=100 연속 3초. DEMO 기본 등급 Error, rpm >=1000 연속 10초 후 관측 회복 |
| M04 | 20초의 21개 유효 1초 표본, rpm max-min >30 Warning/>60 Error 상태 3초 지속, 정상 10초 회복 |
| M19 | 승인 기준의 한쪽 비율 >1.25 Warning/>1.50 Error, 다른 쪽 <=1.10, 같은 측 10초 지속. 두 비율 <=1.10 연속 10초 회복 |
| P03/P04 | 관측된 true >3초 Warning/>5초 Error, false 2초 회복. P04는 downstream_ready 확인도 필요 |
| P01 | 동기화된 FIFO의 미도착 >16초 Error, 추가 지속시간 없음 |
| P02 | 유효 이송 <14초 Warning, 60초 내 최근 5개 중 3회 Error. 연속 정상 매칭 5회 회복 |
| P05 | 연속 투입 기대 시 4~6초 밖 Warning, 최근 5간격 중 3회 Error. 다음 투입 없음 >6초 Warning/>10초 Error. 정상 5간격 회복 |
| P06 | 동기화된 재공 존재·RUN·수신 가능, 출구 이벤트 없음 >16초 Error |
| P07 | 동일 recipe·하중, 60초 내 비중첩 5개 이송 창의 median >15.5 또는 max-min >2초 Warning, 연속 2개 이상 창 Error. 비중첩 정상 창 2개 회복 |
| D01 | 유효 레코드에서 미지원 schema_version 확인. 원시 컬럼·타입·식별 오류는 수집 계층 책임 |
| D02 | 수치 결측·NaN·무한대·invalid_fields 감지, 관련 센서 룰 Unknown |
| D03 | 표본 간격 >2초 감지, 연속성 단절. 시간 역행·동일 ID 충돌은 예외로 격리 |
| D04 | 초기 추적 불명·빈 큐의 출구·만료 후 늦은 출구로 추적 신뢰성 부족 기록 |
| D05 | 수치 룰 평가에 필요한 운전·비교 문맥 미확보 기록 |

정의서가 데이터 품질 코드의 등급·회복 지속시간을 지정하지 않아, 내장 D 진단은
DEMO 정책으로 Warning 즉시 기록/명시적 유효 상태 즉시 회복을 사용한다.
설비 룰의 Unknown 자체를 Error로 바꾸지 않는다. 원시 형식 오류·외부 ID 허용목록 검증,
LIVE 무수신 watchdog과 문맥 유효기간 검증은 수집/PLC 어댑터에서 수행하고 필요하면
`process_assessments`로 D 코드를 전달한다. 원본 TelemetryRecord 없이 Manager를 호출하는
인터페이스는 이번 변경에 포함하지 않았다.

## 문맥

필요한 항목만 제공하며, 없는 값은 추측하지 않는다.

| 키 | 용도 |
|---|---|
| `run_cmd` | True일 때 운전 의존 룰 활성화 |
| `run_started_at` | 시간대 포함 datetime 또는 ISO8601. 기동·예열 경과시간 |
| `fixed_speed` | RPM 고정 속도 조건 확인 |
| `same_load` | 전류 및 이송 추세의 동일 하중 조건 확인 |
| `vibration_comparable` | 진동의 동일 속도·하중·장착·특징 추출 조건 확인 |
| `recipe_id`, `config_version` | 조건 변경 시 후보·시간창·추적 초기화 |
| `vibration_baseline` | M19의 `de`, `nde` 양수 중앙값, `approved=True`, `version`. 검증된 10분 정상 로그 확보는 호출자 책임 |
| `planned_hold`, `maintenance_mode` | True이면 P 및 운전 의존 M 판정 Suppressed. 유효 전압은 계속 평가 |
| `continuous_infeed` | P05 연속 투입 기대 조건 |
| `events_reliable` | PLC 원천 펄스 누락이 없다는 확인. 상태 표본만으로 추정하지 않음 |
| `tracking_reset` | 비어 있음이 확인된 구간에서 한 번 True 전달. 양쪽 센서 false일 때 FIFO 재동기화 |
| `downstream_ready` | P04 회복·P06 평가에 필요한 후속 수신 가능 여부 |
| `inspection_confirmed` | 추적/물리 점검 확인. 재동기화 후 재공이 없을 때 P01/P06 관측 회복 허용 |
| `telemetry_valid`, `invalid_fields` | 전체 입력 또는 특정 센서 품질 무효. 정상으로 간주하지 않음 |

전체 입력 무효·필수 문맥 미확보·시간 공백은 후보 및 회복 타이머를 끊고 확정 사건은
유지한다. 동일 레코드 재수신은 멱등 처리한다. Error는 회복 전 Warning으로 낮추지 않는다.
회복 대기에서는 last_detected_at을 갱신하지 않고 회복 시 마지막 이상 근거를 보존한다.

## 추적과 사건의 범위

현재 원본 CSV는 초기 재공이 불명확하므로 P01/P02/P06/P07을 확정할 수 없다.
추적은 비어 있음 확인과 신뢰 가능한 원천 이벤트가 있어야 시작한다. 만료 트레이는
삭제해 다음 트레이로 넘기지 않고, 늦은 출구가 오면 재동기화가 필요하다.

Manager의 키는 `(process_id, asset_id, rule_code)`다. 복합 룰 사건 묶기·트레이별 사건
분리·tray_seq/config_version/plc_context의 Incident 저장은 기존 Manager API가 지원하지
않으므로 유지한다. RECOVERED와 점검 승인·CLOSED 종결은 다르다.

## 검증과 JSON 시연

`uv run --no-sync python scripts/demo_incident_json.py`는 기본 RuleDetector로 CSV를 평가한다.
RUN과 입력 유효성만 가정하고 추가 문맥은 만들어 넣지 않는다. 변경된 사건을
`outputs/incidents/<사건 ID>/`에 순서대로 저장한다. 기본 CSV P03은 t24 Warning,
t26 Error, t32 회복이다. 다른 룰·품질 진단도 조건이 충족되면 같은 JSON 경로를 사용한다.
Agent/RAG 호출은 수행하지 않는다.
