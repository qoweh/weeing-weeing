# 센서 기반 미래 60초 첫 Error 예측 — 첫 실험

이 모듈은 기준 시각 `t`의 최근 `(t-30초, t]` 센서 10개만 사용해
`(t, t+60초]` 안에 **최초로 발생할 Error Code**를 예측한다.
정확히 60초 뒤 상태나 현재 Warning/Error 분류를 예측하는 태스크가 아니다.
현재 판정은 기존 Detector 책임이다. 첫 오프라인 실험에는 서버 연결을 포함하지 않았다.
후속 요청에 따른 실시간 관찰 통합과 배포는 [ML_LIVE](ML_LIVE.md)를 따른다.

## 설치와 재현

실험 작업 트리는 `.claude/worktrees/ml-first-experiment`, 브랜치는
`feat/ml-first-experiment`이다. 2026-11-04에 가져온 `origin/dev`의 `d1a6fc9`에서 시작했다.
기존 작업 트리의 `feat/chat-search-timings` 브랜치와 미커밋 변경을 그대로 보존했다.
이하 명령은 이 실험 작업 트리 루트에서 실행한다. `.env`와 외부 API는 필요 없다.
Python 3.12, 잠금 의존성은 `uv.lock`을 따른다.

```bash
uv sync --locked --no-install-project --group ml
# 실제 파일을 찾은 뒤 경로를 명시한다. 기본 경로를 가정하지 않는다.
# 이번 PC에서 확인한 원본:
# /Users/boyeong/Desktop/hanwha-ac/project/conveyor_dataset.csv
export PYTHONPATH="$PWD/src"
uv run --no-sync python -m weeing_weeing.ml.experiment validate \
  --csv /실제/경로/conveyor_dataset.csv --output outputs/ml-validation.json
uv run --no-sync python -m weeing_weeing.ml.experiment train \
  --csv /실제/경로/conveyor_dataset.csv --output outputs/ml/future60-v1
uv run --no-sync pytest tests/ml
make check
```

`train` 명령이 검증·분리·window 생성·네 모델 학습·검증 선택·최종 시험 평가·추론 벤치마크를 모두 수행한다.
기존 출력 폴더가 있으면 실패하므로 재현 시 새 `--output`을 지정한다.
같은 데이터의 분리를 명시적으로 고정하려면 아래처럼 기존 manifest를 전달한다.

```bash
uv run --no-sync python -m weeing_weeing.ml.experiment train \
  --csv /실제/경로/conveyor_dataset.csv --output outputs/ml/reproduction-01 \
  --manifest data/eval/ml_future60_v1/split_manifest.json
```

CSV 원본은 읽기만 했다. SHA-256은
`26ed78c3c1eb53d15e6aba9fa752b6aad8f70d16921033867c22594be03086a1`이다.
CSV 전체를 Git에 추가하지 않는다. 원본 CSV, `data/ml/raw/`, joblib,
`outputs/`는 ignore한다. 모델은 로컬 `outputs/ml/future60-v1/model.joblib`에 보관하며,
용량이 큰 이진 산출물은 프로젝트의 별도 저장소 정책이 정해지면 그 정책으로 공유한다.
재현 가능한 평가 증거는 `data/eval/ml_future60_v1/`에 보관했다.

## 데이터 검증과 분리

UTF-8 BOM으로 읽고 컬럼 17개와 순서를 검사한다. 센서 문자열 `true/false`는 명시적으로
1/0으로 변환하며 숫자 문자열 `0/1`이나 다른 값은 bool로 추측하지 않는다.
timezone이 없는 시각은 거부하고, timezone이 있는 시각은 UTC로 정규화한다.
record_id 중복·빈 ID, 알 수 없는 라벨·run_id 형식, 실행 시나리오와 충돌하는 고장 라벨,
실행 내부 asset/process/schema 변경은 데이터 오류로 중단한다.
센서 결측·비유한값·잘못된 bool은 감사 결과에 세고 해당 입력 구간을 제외한다.

이번 실제 파일은 37,274행, 코드별 15개씩 60개 실행이다.
원본 라벨은 NO_ERROR 16,185, M02 1,794, M07 1,797, M10 1,797, M12 1,792,
빈 라벨 13,909로 전달 수치와 일치한다. record_id 중복, 센서 결측/비유한값/형식 오류,
실행 내부 timestamp 중복·역순, 0.8초 초과 공백 모두 0건이다.
표본 간격은 0.132~0.534초다. CSV 자체에는 빈 라벨의 사유 컬럼이 없으므로
'이미 Error 6,697행 / 미래 부족 7,212행'은 제공받은 수집 기록이며 독립 검증하지 못했다.

`run_id`에서 `ml-(M02|M07|M10|M12)-fault-...` 시나리오만 추출해 층화한다.
행의 target_label로 실행 종류를 판단하지 않는다.
실행 목록을 정렬한 뒤 seed `20261104`로 코드별 9/3/3개를 학습/검증/시험에 배정한다.
분리 후 구간을 생성한다. manifest는 원본 SHA-256과 실행 목록을 보관하고
세트 간 중복·누락·코드별 배정 수를 재검사한다. 시험 결과로 분리를 다시 고르지 않았다.

## 시간 구간과 특징 정의

각 실행의 첫 시각부터 3초 간격의 시간 grid를 만든다.
각 grid 이하의 마지막 실제 표본 시각을 `t`로 사용하므로 작은 지터에 따라
실제 기준 시각 간 차이는 정확히 3초가 아닐 수 있다. 행 번호로 구간을 자르지 않는다.
입력은 엄격히 `(t-30초, t]`, 정답은 **그 마지막 실제 표본의 기존 target_label**이다.
원본 행을 유지해서 구간과 특징을 만든 뒤 마지막 라벨이 빈 경우에만 제외한다.
빈 라벨을 NO_ERROR로 채우거나 추가 60초 shift를 적용하지 않는다.

허용 조건은 다음과 같다.

- 원본 이력이 t-30초 이전 또는 동일 시각까지 존재해야 한다. 초기 30초 미만은 준비 안 됨이다.
- 구간 안 유효 표본은 55~65개, 첫 입력~마지막 입력 관측 길이는 29.2초 이상이다.
- 표본 간격은 0.8초 이하이며 왼쪽 경계 직전 표본→첫 입력 간격도 검사한다.
  epoch float 연산 오차에는 1마이크로초 여유만 둔다.
- 중복·역순 시각은 허용하지 않는다. 원본 실행에서 발견하면 보수적으로 그 실행의 모든 후보를 제외한다.
  온라인 함수도 전달된 과거 버퍼의 순서를 검사한다. 자동 정렬로 오류를 숨기지 않는다.
- 구간 센서/특징의 NaN·무한값·잘못된 형식은 제외한다. 보간·대체·실행 간 연결은 하지 않는다.
- 검사는 시간/품질→마지막 라벨 순서이며, 후보당 최초 실패 사유 하나를 집계한다.

`features.extract_features()`를 학습·추론이 공통 사용한다. 입력 순서와 56개 특징명은
`metadata.json`의 `feature_names`에 저장한다. 순서는 아래와 같다.

1. 연속형 8개: rpm, dc_input_current_a, dc_bus_voltage_v, motor_housing_temp_c,
   de_vibration_rms_g, de_kurtosis, nde_vibration_rms_g, nde_kurtosis.
   센서별 current, mean, min, max, std, slope_per_second 순서다(48개).
2. 광전센서 2개: infeed_present, outfeed_present.
   센서별 current, true_ratio, rising_count, falling_count 순서다(8개).

현재값은 마지막 입력값, 평균/True 비율은 표본 산술평균, 표준편차는 모집단 기준(ddof=0),
상승/하강은 구간 내 인접 표본의 false→true/true→false 횟수다.
기울기는 실제 timestamp 초 단위의 최소제곱 직선 기울기
`sum((s-mean(s))*(x-mean(x))) / sum((s-mean(s))**2)`다.
왼쪽 경계 표본은 이력 확보 검증 전용으로 특징/전이 횟수에 포함하지 않는다.
`t` 이후의 센서, 라벨, run_id, record_id, timestamp 자체, 관리 정보,
실행 시작 후 경과시간, 실행 순서는 특징에 넣지 않는다.
별도의 학습 전처리 객체는 필요 없으며 scaler/imputer는 사용하지 않았다.

## 모델 선택과 확률 해석

RandomForest 200 trees, `min_samples_leaf ∈ {1,3}`, seed 고정, `n_jobs=1`을 사용한다.
원본 학습 분포와 NO_ERROR : 고장 전체 = 50:50 비복원 축소 분포를 비교한다.
이번 50:50 실험은 NO_ERROR만 1,228→720개로 축소했고 고장은 코드별 180개를 유지했다.
검증·시험은 샘플링하지 않는다. 학습은 학습 세트만 사용하고 검증을 합쳐 재학습하지 않는다.

경고 기준 `P(Error)=1-P(NO_ERROR)`의 임계값 `{0.3,0.5,0.7}`을 검증에서 비교했다.
임계값 이상이면 가장 높은 고장 확률 코드, 미만이면 NO_ERROR로 최종 분류한다.
보고된 Accuracy/F1/행별 prediction/confusion matrix는 이 정책의 결과다.
**단순 5클래스 argmax 평가가 아니다.** Macro F1 최대, 동률이면 NO_ERROR 오경고율 최소,
다시 동률이면 고정 순서의 첫 후보를 택한다. 검증 12개 비교 결과는
`validation_candidates.json`에 모두 있다. 시험은 선택 후 최종 정책 하나만 평가했다.

확률 보정은 하지 않았다. 각 코드 확률은 '향후 60초 이내 최초 Error가 그 코드일 모델 예측 확률'이며,
실제 발생 빈도와 동일하다고 검증된 확률이 아니다. 학습 분포 변경도 확률에 영향을 줄 수 있다.
Top 3는 NO_ERROR를 제외한 네 고장 중 상위 세 개이며 합계 100%로 재정규화하지 않는다.

## 백엔드용 추론

모듈 외부에서는 `ml.interface`만 import한다. 프로세스 시작 때 한 번 모델을 로드하고
설비·실행별 독립 버퍼를 유지한다. 버퍼는 최소 30초를 확보하고 왼쪽 경계 이전/동일 표본
하나를 남겨야 한다(정상 0.5초 간격에서는 약 61개 이상).
입력 실행 전환·재시작 때 버퍼를 비운다. 새 표본마다 0.5초 주기로 함수를 호출할 수 있고
호출 중 재학습은 없다. 구간 stride 3초는 오프라인 학습/평가에만 적용한다.

```python
from weeing_weeing.ml.interface import FutureErrorPredictor

predictor = FutureErrorPredictor.load("outputs/ml/future60-v1/model.joblib")
# recent_rows: timestamp(UTC ISO 문자열 또는 aware datetime) + 센서 10개 dict 목록
result = predictor.predict(recent_rows)
# 기준 시각을 명시할 수도 있다. 그 시각은 실제 마지막 입력 표본과 일치해야 한다.
# result = predictor.predict(recent_rows, as_of=reference_time)
```

정상 반환에는 status=ready, input_valid=true, reference_time, model_version,
품질 정보, 전체 5개 probabilities, no_error_probability, error_probability,
fault_top3[{code, confidence}], warning_threshold, warning, probability_kind가 있다.
`model.classes_` 순서로 확률을 코드에 매핑하며 클래스 순서를 가정하지 않는다.
이력이 짧으면 status=not_ready, 시간/품질 오류면 invalid_input으로 반환한다.
부적합 입력에는 probabilities=null이며 임의의 정상 확률을 만들지 않는다.
현재 이미 Error인지와 예측 표시 가능 여부는 이후 서버 연결 시 Detector 상태와 함께 설계해야 한다.
joblib은 pickle 기반이므로 신뢰하는 로컬 모델만 로드한다.

대상 장비에서 재학습 없이 벤치마크를 다시 실행할 수 있다.

```bash
uv run --no-sync python -m weeing_weeing.ml.experiment benchmark \
  --csv /실제/경로/conveyor_dataset.csv \
  --model outputs/ml/future60-v1/model.joblib \
  --manifest outputs/ml/future60-v1/split_manifest.json \
  --output outputs/ml/target-device-benchmark.json
```

이번 현재 개발 PC(macOS arm64, Python 3.12.12)에서 순차 200회 측정했다.
특징 계산 평균 0.242ms / P95 0.284ms, predict_proba 평균 3.672ms / P95 3.883ms,
전체 함수 평균 3.903ms / P95 4.188ms / 최대 4.589ms로 측정 호출은 모두 500ms 이내다.
워밍업 5회 이후 서로 다른 시험 구간을 순회했다. 서버 동시 부하·스케줄링·현장 장비에서는
미확인이므로 실시간 주기를 보장한다는 의미는 아니다.

## 산출물과 검증

- `outputs/ml/future60-v1/model.joblib`: 학습 모델과 메타데이터 번들(약 589KB).
- `metadata.json`: 모델 버전, 소스 해시, 특징 순서/정의, classes_, window 조건, 선택 설정, 라이브러리 버전.
- `split_manifest.json`: seed, CSV 해시, 세트별 모든 run_id.
- `data_validation.json`, `window_summary.json`: 원본 검사, 코드별/실행별 원본 행·window·제외 사유·클래스 분포.
- `validation_candidates.json`: 검증 비교 12개. `evaluation.json`: 세트별/실행별 상세 지표와 벤치마크.
- `*_predictions.csv`, `*_confusion_matrix.csv`: 기준 시각·정답·최종 예측 및 혼동행렬.
- `artifact_checksums.json`: 산출물 무결성 확인용 SHA-256.

읽기 쉬운 수치 요약은 [ML_FUTURE_ERROR_RESULTS](ML_FUTURE_ERROR_RESULTS.md)에 있다.
`tests/ml/test_future_error.py`는 실행 분리/manifest 중복, 시간 경계, bool/UTC,
초기 부족/공백/중복/역순/NaN/혼합 실행, 빈 라벨 유지 후 endpoint 제외,
관리 정보/미래 센서 누설 방지, 학습·온라인 특징 일치, classes_ 확률 매핑을 검증한다.

## 해석의 한계와 미확인 사항

겹치는 window는 독립 사건이 아니며 코드별 시험 실행은 3회뿐이다.
window 수준 고장 Recall이 높아도 실제 설비 성능이나 사건 검출률로 표현할 수 없다.
모든 수치는 Unreal 합성 시뮬레이션에 한정된다.
별도의 Warning 후 회복 전용 실행이 없어 그런 상황의 오경고·일반화는 확인되지 않았다.

CSV에 실제 Error 진입 이벤트 시각이 없다. 정확한 선행시간과 사건별 경고 지속시간은
Detector 이벤트 기록을 run_id/timestamp로 연결해야 평가할 수 있다.
빈 라벨 시작점은 이미 Error와 미래 관측 부족을 구분할 수 없으므로 Error 시각으로 확정하지 않았다.
실제 공장 데이터, 다른 운전 조건/설비, 확률 보정, 운영용 오경고 허용 기준은 미검증이다.
