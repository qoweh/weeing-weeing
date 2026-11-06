# 미래 60초 Error 예측: 15개 고장 유형 통합 학습

2026-11-06, 기존 CSV와 11종 추가 CSV를 함께 읽어 RandomForest를 새로 학습했다. 기존 모델에 트리를 덧붙이는 방식은 사용하지 않았다. 원본 CSV, 기존 모델, AWS 배포는 변경하지 않았다. 작업 브랜치는 `feat/242-ml-expanded-training`이다. 실제 `.env` 파일은 읽지 않았다.

## 코드와 재현 명령

- 학습·후보 비교·평가: `src/weeing_weeing/ml/experiment.py`의 `train()` 및 CLI `main()`.
- 파일별/통합 검증·실행 분리·window 생성: `src/weeing_weeing/ml/data.py`.
- 공통 특징 계산과 시간/품질 조건: `src/weeing_weeing/ml/features.py`.
- 저장 모델 로드·실시간 추론: `src/weeing_weeing/ml/interface.py`의 `FutureErrorPredictor`.
- 실시간 결과의 지원 코드 목록: `src/weeing_weeing/ml/live.py`에서 로드한 모델 기준으로 제공한다.

실제 파일 경로를 확인한 후 다음을 실행한다. `.env` 자동 로드는 끈다. 출력 폴더는 새 이름을 사용한다.

```bash
cd /Users/boyeong/Desktop/hanwha-ac/project/ml-expanded-training
uv sync --locked --no-install-project --group ml

PYTHONPATH=src uv run --no-env-file --no-sync python -m weeing_weeing.ml.experiment validate \
  --csv ../conveyor_dataset.csv \
  --csv ../conveyor_dataset_11set.csv \
  --output outputs/ml/expanded_validation.json

PYTHONPATH=src uv run --no-env-file --no-sync python -m weeing_weeing.ml.experiment train \
  --csv ../conveyor_dataset.csv \
  --csv ../conveyor_dataset_11set.csv \
  --extend-manifest data/eval/ml_future60_v1/split_manifest.json \
  --output outputs/ml/future60-15faults-reproduction
```

`--csv`를 여러 번 지정하면 파일별 스키마·라벨·시간·센서를 검증한 후 통합한다. 파일 사이 record_id/run_id 중복은 조용히 제거하지 않고 오류로 보고한다. run_id의 시나리오 코드와 비어 있지 않은 고장 라벨도 대조한다. 등록된 물리 고장 코드만 허용하고, 실제 데이터에서 발견한 클래스를 메타데이터에 저장한다. 현재 분리 규칙은 코드당 15회 실행의 9/3/3이므로 실행 수가 다른 후속 데이터는 규칙을 별도로 검토해야 한다.

`--extend-manifest`는 원본 파일 해시와 기존 실행을 검증하고 기존 60개 실행의 세트 배정을 그대로 보존한다. 새 165개 실행만 고정 seed로 분리한다. 완성된 분리를 그대로 재사용할 때는 `--extend-manifest` 대신 `--manifest outputs/ml/future60-15faults-v2-20261106/split_manifest.json`을 사용한다. 시험 결과를 보고 분리를 다시 고르지 않았다.

## 확인한 데이터

| 파일 | 원본 행 | 실행 | 고장 종류 |
|---|---:|---:|---:|
| conveyor_dataset.csv | 37,274 | 60 | 4 |
| conveyor_dataset_11set.csv | 100,920 | 165 | 11 |
| 합계 | 138,194 | 225 | 15 |

현재는 **고장 15종 + NO_ERROR = 16개 클래스**다. 17종 고장 전체가 확보된 상태는 아니다.

고장 코드: M02, M03, M05, M06, M07, M08, M10, M11, M12, M13, M14, M15, M16, M17, M18 (모두 `BTT2-` 접두어).

두 파일 모두 동일한 17개 컬럼이며, 중복 record_id/run_id, 센서 결측·비유한값, 중복·역순 timestamp, 0.8초 초과 공백은 발견되지 않았다. 표본 간격은 0.132~0.718초였다. 기존 CSV의 사용자 제공 원본 행/라벨 수와 차이는 없었다. 파일별 SHA-256과 상세 검증은 `data_validation.json`에 있다.

입력은 기존과 같은 센서 10개뿐이다. run_id, timestamp, 경과시간, 실행 순서, 관리 정보는 특징에 넣지 않는다. timestamp는 UTC aware로 처리하고 true/false는 명시적으로 변환한다.

구간 `(t-30초,t]`, 학습 stride 3초, 55~65표본, 관측 길이 29.2초 이상, 최대 공백 0.8초 이하를 요구한다. 왼쪽 경계 이전 또는 경계의 관측이 있어야 한다. 원본 행을 보존해 구간을 구성한 다음 마지막 라벨이 비면 제외한다. 빈 라벨을 정상으로 채우거나 추가 60초 shift를 적용하지 않는다. 특징 순서·정의는 `metadata.json`과 [기존 특징 설명](ML_FUTURE_ERROR.md)에 있다.

## 분리 및 window 집계

| 세트 | 실행 | 원본 행 | 후보 구간 | 유효 라벨 window | 초기 이력 부족 | 마지막 빈 라벨 |
|---|---:|---:|---:|---:|---:|---:|
| 학습 | 135 | 82,824 | 13,837 | 7,247 | 1,485 | 5,105 |
| 검증 | 45 | 27,658 | 4,623 | 2,430 | 495 | 1,698 |
| 시험 | 45 | 27,712 | 4,627 | 2,425 | 495 | 1,707 |

각 코드별 실행은 학습 9/검증 3/시험 3이며 세트 간 run_id 중복이 없다. 코드별 원본 행·window 수·제외 사유와 세트별 클래스 분포는 `window_summary.json`에 보존했다. 다른 품질 사유로 제외된 구간은 0개다.

## 모델 선택 및 평가

200트리 RandomForest에서 min_samples_leaf 1/3, 원본 분포/학습 NO_ERROR 다운샘플링을 비교했다. 경고 임계값도 검증 세트로 선택했다. 선택 결과는 leaf 3, 학습 정상:고장 전체 1:1(각 2,692 window), P(Error) 임계값 0.5다. 검증·시험에는 샘플링하지 않았다. 평가 클래스는 P(Error)가 임계값 이상이면 고장 중 최대 확률 코드, 미만이면 NO_ERROR로 정한다.

| 세트 | Accuracy | Macro F1 | NO_ERROR 오경고율 |
|---|---:|---:|---:|
| 학습 | 98.56% | 98.14% | 1.91% |
| 검증 | 93.50% | 91.63% | 6.76% |
| 시험 | 94.72% | 93.27% | 5.89% |

시험 클래스별 결과:

| 클래스 | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| NO_ERROR | 97.43% | 94.11% | 95.74% | 1528 |
| BTT2-M02 | 85.71% | 100.00% | 92.31% | 60 |
| BTT2-M03 | 93.33% | 93.33% | 93.33% | 60 |
| BTT2-M05 | 88.24% | 100.00% | 93.75% | 60 |
| BTT2-M06 | 98.21% | 91.67% | 94.83% | 60 |
| BTT2-M07 | 85.71% | 100.00% | 92.31% | 60 |
| BTT2-M08 | 96.49% | 91.67% | 94.02% | 60 |
| BTT2-M10 | 83.33% | 100.00% | 90.91% | 60 |
| BTT2-M11 | 90.48% | 95.00% | 92.68% | 60 |
| BTT2-M12 | 90.16% | 93.22% | 91.67% | 59 |
| BTT2-M13 | 87.50% | 94.92% | 91.06% | 59 |
| BTT2-M14 | 87.88% | 98.31% | 92.80% | 59 |
| BTT2-M15 | 100.00% | 95.00% | 97.44% | 60 |
| BTT2-M16 | 89.23% | 96.67% | 92.80% | 60 |
| BTT2-M17 | 88.06% | 98.33% | 92.91% | 60 |
| BTT2-M18 | 100.00% | 88.33% | 93.81% | 60 |

시험 NO_ERROR 1,528개 중 고장 예측 90개, 고장 window 897개 중 NO_ERROR 예측 38개였다. 고장을 다른 고장 코드로 예측한 window는 이번 시험에서 0개였다. 다른 데이터에서도 혼동이 없다는 뜻은 아니다.

정확한 혼동행렬은 `test_confusion_matrix.csv`(행=정답, 열=예측), 실행별 평가는 `evaluation.json`의 각 세트 `per_run`에 있다. 실행별 Macro F1도 전체 16개 클래스를 기준으로 하므로 해당 실행에 없는 클래스의 0점이 포함된다. 실행별 비교는 Accuracy·오경고율·해당 고장 Recall을 함께 본다.

## 모델 사용과 산출물

실제 학습 출력: `outputs/ml/future60-15faults-v2-20261106/`.

- `model.joblib`: 학습 모델과 메타데이터를 담은 번들, 약 2.14MB.
- `metadata.json`: 특징 순서, 실제 모델 클래스 순서, 구간 조건, 버전, 학습 설정, 소스/데이터 해시.
- `split_manifest.json`: 실행별 세트 배정과 기존 분리 보존 기록.
- `data_validation.json`, `window_summary.json`, `validation_candidates.json`, `evaluation.json`, 세트별 혼동행렬·행별 예측, `artifact_checksums.json`.

원본 CSV와 모델/행별 예측은 Git에서 제외한다. 원본 센서 행을 포함하지 않는 평가·메타데이터 사본은 `data/eval/ml_future60_v2_15faults/`에 보존했다. 이 사본의 `evidence_checksums.json`은 사본 파일들의 해시와 외부 모델 파일의 해시를 구분한다.

```python
from weeing_weeing.ml.interface import FutureErrorPredictor

predictor = FutureErrorPredictor.load(
    "outputs/ml/future60-15faults-v2-20261106/model.joblib"
)
result = predictor.predict(recent_rows)  # UTC timestamp와 센서 10개를 포함한 최근 입력
```

모델 로드는 한 번만 하고 새 표본마다 `predict()`를 호출한다. 학습과 추론이 같은 특징 함수를 사용한다. 확률은 실제 `model.classes_` 순서로 매핑하며, 전체 클래스 확률·P(NO_ERROR)·1-P(NO_ERROR)·고장 Top 3·지원 코드·유효 상태를 반환한다. Top 3는 재정규화하지 않는다. 입력이 준비되지 않으면 정상 확률을 생성하지 않는다. v1 모델의 호환 경로도 유지했다.

모델 버전: `rf-future60-v2-6ae992008f6f`. 확률 보정을 하지 않은 모델 예측 확률이다.

## 검증과 해석의 한계

`UV_NO_ENV_FILE=1 make check`: 1,817 passed, 7 skipped. 기존 통합 테스트 경고 3개가 있었다. 추가 검증은 다중 CSV 중복/라벨 검증, 기존 실행 분리 보존, 클래스 확장, 저장/로드 확률 매핑 및 기존 시간 경계·빈 라벨·특징 일치 테스트를 포함한다.

이 개발 Mac(arm64)에서 200회 측정한 전체 특징 계산+추론은 평균 3.89ms, p95 4.01ms, 최대 5.10ms였다. 0.5초보다 짧지만 AWS 부하 환경이나 실시간 주기 보장을 검증한 결과는 아니다.

겹치는 window는 독립 사건이 아니고 코드당 시험 실행은 3회뿐이다. Unreal 합성 데이터의 성능이며 실제 공장 성능으로 해석할 수 없다. 별도 Warning 후 회복 전용 실행과 완전히 정상으로 끝나는 독립 실행은 이번 데이터에서 따로 평가하지 않았다. NO_ERROR 오경고율은 NO_ERROR로 라벨된 구간 기준이며 정상 실행 전체의 오경보 사건율이 아니다. 실제 Error 이벤트 시각 컬럼이 없어 정확한 선행시간 평가는 하지 않았다. 빈 라벨 시작을 Error 시각으로 확정하지 않았으며, 선행시간 평가에는 Detector 이벤트 기록이 필요하다. 이전 4종 모델과는 시험 대상 클래스가 달라 전체 지표의 단순 비교로 개선을 주장하지 않는다.

## 확률 평가 추가 (2026-11-06)

기존 모델을 재학습·보정하지 않고 동일한 9/3/3 실행 분리에서 확률 지표를 추가 측정했다. 기존 모델과 최초 평가 산출물은 덮어쓰지 않았다. 이후 `train`의 `evaluation.json`에는 `probability_metrics`가 자동 포함된다. 모델 선택은 기존 검증 Macro F1 기준을 유지하므로 지표 추가만으로 학습 목표나 예측 확률이 달라지지는 않는다.

```bash
PYTHONPATH=src uv run --no-env-file --no-sync python -m weeing_weeing.ml.experiment evaluate-probabilities \
  --csv ../conveyor_dataset.csv \
  --csv ../conveyor_dataset_11set.csv \
  --manifest outputs/ml/future60-15faults-v2-20261106/split_manifest.json \
  --model outputs/ml/future60-15faults-v2-20261106/model.joblib \
  --output outputs/ml/future60-15faults-probabilities-new.json
```

실제 결과 원본: `outputs/ml/future60-15faults-probabilities-20261106.json`.

| 세트 | window | Log Loss | 다중 클래스 Brier | 전체 Error Brier | 전체 Error ECE |
|---|---:|---:|---:|---:|---:|
| 학습 | 7,247 | 0.06386 | 0.02833 | 0.01426 | 0.03499 |
| 검증 | 2,430 | 0.20824 | 0.10523 | 0.05330 | 0.02966 |
| 시험 | 2,425 | 0.15916 | 0.08362 | 0.04258 | 0.04250 |

- Log Loss: 정답 클래스 확률의 자연로그 손실. 0 확률은 float64 epsilon으로 제한하며 낮을수록 좋다.
- 다중 클래스 Brier: 클래스별 `(예측 확률−정답 0/1)^2`을 합산한 뒤 window 평균. 범위 0~2이며 클래스 수로 나누지 않는다.
- 전체 Error Brier: `1−P(NO_ERROR)`와 실제 향후 60초 내 Error 여부의 제곱 오차 평균. 범위 0~1.
- 코드별 Brier와 신뢰도 구간도 제공한다. `[0,0.1) … [0.9,1]` 동일 너비 10구간마다 표본 수·평균 예측 확률·실제 양성 비율을 기록한다. 빈 구간은 null이고 0% 발생으로 해석하지 않는다.
- ECE는 구간별 예측 평균과 발생 빈도 차이의 표본 수 가중 평균이다. 0에 가까울수록 구간 평균이 가깝지만 구간 선택·표본 수에 민감하며, 낮은 ECE 하나로 좋은 모델이라 단정하지 않는다. 클래스 희소성 때문에 코드별 Brier도 단독으로 판단하지 않는다.

요약/신뢰도 구간은 `data/eval/ml_future60_v2_15faults/probability_evaluation.json`, 실행별 집계는 `probability_per_run.csv`다. 원본 출력에는 실행별 전체 신뢰도 구간도 있다. 모델 클래스 순서를 직접 사용하며 데이터 해시·manifest 및 모델 해시를 결과에 기록한다. 전체 세트의 각 window에 동일 가중치를 사용하며 실행마다 동일 가중치를 부여한 점수는 아니다.

현재 확률은 미보정 합성 데이터 확률이다. 정상 50% 학습 샘플링·의도적 고장 수집 비율과 실제 운영 발생 비율은 다를 수 있다. 이번 점수만으로 실제 공장 발생 확률의 정확성을 입증하지 않는다. 겹치는 window의 상관성, 코드당 시험 3회, 별도 정상 종료·Warning 후 회복 실행 부족의 한계도 그대로다.

확률 지표 추가 후 `UV_NO_ENV_FILE=1 make check`는 1,827 passed, 7 skipped, 기존 경고 3개로 통과했다. 최초 제한 환경에서 기존 WebSocket 테스트 3개가 localhost bind 권한 오류로 실행되지 않았고, localhost를 허용해 전체 검사를 다시 통과시켰다. ML 테스트 37개도 별도로 통과했다. 기존 모델·manifest·평가 산출물 13개 해시의 불변성과 확률 구간/실행별 표본 수 합계를 확인했다. `.env`는 로드하지 않았다.

## NO_ERROR 포함 전체 Top 1 분류 비교 (2026-11-06)

동일한 저장 모델과 고정 분리에서, 기존 전체 Error 확률 임계값 0.5 방식과 `model.classes_[predict_proba.argmax()]` 방식을 비교했다. Top 1에는 NO_ERROR를 포함한 16개 전체 클래스를 사용한다. 동률은 `model.classes_` 순서의 첫 항목으로 정한다. 실제 이번 모든 세트에서 정확한 최대 확률 동률은 0개였다. 모델 재학습·확률 보정·추론 동작 변경은 하지 않았다.

```bash
PYTHONPATH=src uv run --no-env-file --no-sync python -m weeing_weeing.ml.compare_decisions \
  --csv ../conveyor_dataset.csv \
  --csv ../conveyor_dataset_11set.csv \
  --manifest outputs/ml/future60-15faults-v2-20261106/split_manifest.json \
  --model outputs/ml/future60-15faults-v2-20261106/model.joblib \
  --output outputs/ml/future60-15faults-top1-comparison-new.json
```

| 세트 | 방식 | Accuracy | Macro F1 | NO_ERROR 오경고율 | 전체 Error Recall | 오경고 window | 놓친 고장 window |
|---|---|---:|---:|---:|---:|---:|---:|
| 학습 | 기존 0.5 | 98.56% | 98.14% | 1.91% | 99.37% | 87 | 17 |
| 학습 | 전체 Top 1 | 98.56% | 98.14% | 1.91% | 99.37% | 87 | 17 |
| 검증 | 기존 0.5 | 93.50% | 91.63% | 6.76% | 93.95% | 104 | 54 |
| 검증 | 전체 Top 1 | 93.33% | 91.40% | 6.70% | 93.39% | 103 | 59 |
| 시험 | 기존 0.5 | 94.72% | 93.27% | 5.89% | 95.76% | 90 | 38 |
| 시험 | 전체 Top 1 | 94.76% | 93.32% | 5.76% | 95.65% | 88 | 39 |

시험에서 최종 분류가 바뀐 것은 2,425개 중 3개다. NO_ERROR 2개는 오경고가 해소됐고 M07 1개는 NO_ERROR로 바뀌어 누락됐다. 검증에서는 2,430개 중 6개가 바뀌었고 오경고 1개 감소·누락 5개 증가였다. 학습 세트는 바뀐 분류가 없다. 두 방식 모두 이번 데이터에서는 고장을 다른 고장 코드로 혼동한 구간은 0개다. 전체 Error Recall은 NO_ERROR가 아닌 정답 중 NO_ERROR가 아닌 예측의 비율이며, 클래스별 Recall의 단순 평균이 아니다.

시험에서 변한 고장 코드 Precision/Recall:

| 코드 | 기존 Precision | Top 1 Precision | 기존 Recall | Top 1 Recall |
|---|---:|---:|---:|---:|
| BTT2-M07 | 85.71% | 85.51% | 100.00% | 98.33% |
| BTT2-M08 | 96.49% | 98.21% | 91.67% | 91.67% |
| BTT2-M17 | 88.06% | 89.39% | 98.33% | 98.33% |

M10의 Precision 83.33%·Recall 100% 등 나머지 고장 코드의 시험 Precision/Recall은 동일하다. 전체 클래스별 P/R/F1 비교는 `data/eval/ml_future60_v2_15faults/top1_class_comparison.csv`, 혼동행렬·실행별 결과는 `top1_comparison.json`에 있다. 원본 출력은 `outputs/ml/future60-15faults-top1-comparison-20261106.json`이다.

Top 1 방식은 시험 Accuracy·Macro F1이 극소폭 높지만 검증에서는 두 지표가 소폭 낮았다. 이번 비교만으로 우수성을 단정하거나 운영 분류 방식을 자동 교체하지 않았다. 이미 관찰한 시험 세트에서의 설명적 비교이며 새로운 독립 시험 결과가 아니다. 모델 확률 자체는 동일하므로 Log Loss·Brier·확률 보정 지표도 변하지 않는다. 서로 겹치는 window와 코드당 시험 3회라는 한계는 동일하다.

Top 1 비교 추가 후 전체 검사: `UV_NO_ENV_FILE=1 make check` 1,829 passed, 7 skipped, 기존 경고 3개. 클래스 순서 변경·NO_ERROR 포함·임계값 경계·동률 테스트를 통과했다. 모델 등 기존 산출물 13개 해시는 그대로이고, 클래스 순서를 맞춰 대조한 기존 방식의 혼동행렬은 최초 평가와 세 세트 모두 일치했다.
