import type { MlSnapshot } from "../../api/client";

export type PredictionState = {
  current: MlSnapshot | null;
  lastGood: { snapshot: MlSnapshot; receivedAt: string } | null;
  lost: boolean;
};

export const emptyPredictionState = (): PredictionState => ({
  current: null,
  lastGood: null,
  lost: false,
});

function probability(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
  );
}

function usable(snapshot: MlSnapshot) {
  const p = snapshot.prediction;
  const rows =
    p.fault_top3?.map((row) => row.confidence) ??
    Object.entries(p.probabilities ?? {})
      .filter(([code]) => code !== "NO_ERROR")
      .map(([, value]) => value);
  return (
    snapshot.enabled &&
    snapshot.producer_connected &&
    !snapshot.stale &&
    snapshot.prediction_usable &&
    p.status === "ready" &&
    p.input_valid !== false &&
    p.evaluation_eligible !== false &&
    !p.deadline_exceeded &&
    probability(p.error_probability) &&
    rows.length > 0 &&
    rows.every(probability)
  );
}

export function receivePrediction(
  previous: PredictionState,
  snapshot: MlSnapshot,
  receivedAt: string,
): PredictionState {
  const cached = previous.lastGood;
  const sameSource =
    cached &&
    cached.snapshot.run_id === snapshot.run_id &&
    cached.snapshot.model_version === snapshot.model_version;
  return {
    current: snapshot,
    lost: false,
    lastGood: usable(snapshot)
      ? { snapshot, receivedAt }
      : snapshot.enabled && sameSource
        ? cached
        : null,
  };
}

const inputErrors: Record<string, string> = {
  processing_lag: "예측 처리 지연",
  queue_overflow: "예측 처리 대기열",
  timestamp_order: "센서 시각 순서",
  invalid_timestamp: "센서 시각",
  mixed_runs: "센서 세션 혼합",
  invalid_sensor: "센서 입력값",
  nonfinite_sensor: "센서 입력값",
  nonfinite_feature: "예측 특징값",
};

export function predictionDisplay(state: PredictionState) {
  const snapshot = state.current;
  const p = snapshot?.prediction;
  let error = "";
  let notice = "";
  if (state.lost) error = "예측 조회 통신";
  else if (!snapshot) notice = "예측을 준비하고 있습니다.";
  else if (!snapshot.enabled) notice = "예측 기능이 꺼져 있습니다.";
  else if (p?.status === "model_error") error = "ML 모델 로딩";
  else if (p?.status === "inference_error") error = "ML 추론";
  else if (p?.status === "invalid_input") {
    // Short input gaps retain the last forecast without representing it as new inference.
    if (
      [
        "gap_over_0_8s",
        "sample_count",
        "observed_span",
        "anchor_not_sample",
      ].includes(p.reason ?? "")
    )
      notice = "데이터 공백으로 예측 갱신을 기다리고 있습니다.";
    else error = inputErrors[p.reason ?? ""] ?? "예측 입력 데이터";
  } else if (!snapshot.producer_connected || snapshot.stale)
    notice = "센서 수신 지연으로 예측 갱신을 기다리고 있습니다.";
  else if (p?.status === "not_ready" || p?.status === "initializing")
    notice = "예측을 준비하고 있습니다.";
  else if (p?.evaluation_eligible === false)
    notice = "현재 감지된 오류가 있어 미래 예측 갱신을 기다리고 있습니다.";
  else if (p?.deadline_exceeded) error = "예측 처리 시간 초과";
  else if (!usable(snapshot)) error = "예측 응답";

  const held = Boolean(state.lastGood && (error || notice));
  const reference = state.lastGood?.snapshot.prediction.reference_time;
  return {
    prediction: state.lastGood?.snapshot.prediction ?? null,
    held,
    isError: Boolean(error),
    message: error
      ? `${error} 에러가 발생했습니다. 확인이 필요합니다.`
      : notice,
    timestamp: reference || state.lastGood?.receivedAt,
    timestampLabel: reference ? "마지막 예측 시각" : "마지막 결과 수신 시각",
  };
}
