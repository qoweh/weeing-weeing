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
  // 통신·센서 수신 지연 중에는 오래된 그래프를 숨기고, 정상 복귀하면 그래프만 보인다.
  let hideGraph = false;
  let faulted = false;
  if (state.lost) {
    error = "예측 조회 통신";
    hideGraph = true;
  } else if (!snapshot) notice = "예측을 준비하고 있습니다.";
  else if (!snapshot.enabled) notice = "예측 기능이 꺼져 있습니다.";
  else if (p?.status === "model_error") error = "ML 모델 로딩";
  else if (p?.status === "inference_error") error = "ML 추론";
  else if (p?.status === "invalid_input") {
    // Short input gaps retain the last forecast without representing it as new inference.
    if (
      [
        "gap_over_0_8s",
        "gap_over_1_5s",
        "sample_count",
        "observed_span",
        "anchor_not_sample",
      ].includes(p.reason ?? "")
    ) {
      notice = "데이터 공백으로 예측 갱신을 기다리고 있습니다.";
      hideGraph = true;
    } else error = inputErrors[p.reason ?? ""] ?? "예측 입력 데이터";
  } else if (!snapshot.producer_connected || snapshot.stale) {
    notice = "센서 수신 지연으로 예측 갱신을 기다리고 있습니다.";
    hideGraph = true;
  } else if (p?.status === "not_ready" || p?.status === "initializing")
    notice = "데이터를 수집하고 있습니다.";
  else if (p?.evaluation_eligible === false) {
    notice = "이상이 발생하였습니다.";
    faulted = true;
    hideGraph = true;
  } else if (p?.deadline_exceeded) error = "예측 처리 시간 초과";
  else if (!usable(snapshot)) error = "예측 응답";

  // 수신된 예측의 에러 확률이 100%에 도달하면 에러가 발견된 것으로 알린다.
  const found =
    !error &&
    !notice &&
    (state.lastGood?.snapshot.prediction.error_probability ?? 0) >= 1;
  if (found) {
    notice = "이상현상이 발견 되었습니다";
    hideGraph = true; // 정상 복귀(확률 100% 미만)하면 그래프를 다시 보여 준다.
  }

  if (error || notice) hideGraph = true;
  const held = false;
  const reference = state.lastGood?.snapshot.prediction.reference_time;
  return {
    prediction: hideGraph
      ? null
      : (state.lastGood?.snapshot.prediction ?? null),
    held,
    isError: Boolean(error),
    found,
    faulted,
    message: error
      ? `${error} 에러가 발생했습니다. 확인이 필요합니다.`
      : notice,
    timestamp: reference || state.lastGood?.receivedAt,
    timestampLabel: reference ? "마지막 예측 시각" : "마지막 결과 수신 시각",
  };
}
