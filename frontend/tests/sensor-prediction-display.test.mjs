import { test } from "node:test";
import assert from "node:assert/strict";
import { getMlPrediction } from "../src/api/client.js";
import {
  emptyPredictionState,
  receivePrediction,
  predictionDisplay,
} from "../src/components/dashboard/predictionDisplay.ts";

const at = "2026-11-05T06:00:00Z";
function snapshot(overrides = {}, prediction = {}) {
  return {
    run_id: "run-one",
    model_version: "model-one",
    enabled: true,
    producer_connected: true,
    stale: false,
    prediction_usable: true,
    ...overrides,
    prediction: {
      status: "ready",
      input_valid: true,
      evaluation_eligible: true,
      reference_time: at,
      error_probability: 0.292,
      fault_top3: [{ code: "BTT2-M02", confidence: 0.124 }],
      ...prediction,
    },
  };
}
const initial = () => receivePrediction(emptyPredictionState(), snapshot(), at);

test("first load has no invented probabilities or error", () => {
  const view = predictionDisplay(emptyPredictionState());
  assert.equal(view.prediction, null);
  assert.equal(view.isError, false);
  assert.match(view.message, /준비/);
});

test("short gaps keep the original forecast and its original time, then recover", () => {
  const state = initial();
  const original = structuredClone(state);
  const gap = receivePrediction(
    state,
    snapshot(
      { prediction_usable: false },
      {
        status: "invalid_input",
        reason: "gap_over_1_5s",
        input_valid: false,
        reference_time: "2026-11-05T06:00:05Z",
        error_probability: undefined,
      },
    ),
    "2026-11-05T06:00:06Z",
  );
  const view = predictionDisplay(gap);
  assert.equal(view.prediction, null);
  assert.equal(view.timestamp, at);
  assert.equal(view.held, false);
  assert.equal(view.isError, false);
  assert.match(view.message, /데이터 공백/);
  assert.deepEqual(state, original);
  const recovered = predictionDisplay(
    receivePrediction(
      gap,
      snapshot(
        {},
        {
          reference_time: "2026-11-05T06:00:40Z",
          error_probability: 0.1,
        },
      ),
      "2026-11-05T06:00:41Z",
    ),
  );
  assert.equal(recovered.prediction.error_probability, 0.1);
  assert.equal(recovered.held, false);
  assert.equal(recovered.message, "");
});

test("HTTP failure preserves the last result with an explicit error, recovery clears it", () => {
  const lost = { ...initial(), lost: true };
  const view = predictionDisplay(lost);
  assert.equal(view.prediction, null);
  assert.equal(view.held, false);
  assert.equal(view.isError, true);
  assert.equal(
    view.message,
    "예측 조회 통신 에러가 발생했습니다. 확인이 필요합니다.",
  );
  assert.equal(
    predictionDisplay(receivePrediction(lost, snapshot(), at)).isError,
    false,
  );
});

for (const [status, expected] of [
  ["model_error", "ML 모델 로딩"],
  ["inference_error", "ML 추론"],
]) {
  test(`${status} is an error even when the server marks the result stale`, () => {
    const state = receivePrediction(
      initial(),
      snapshot({ stale: true, prediction_usable: false }, { status }),
      at,
    );
    const view = predictionDisplay(state);
    assert.equal(view.isError, true);
    assert.equal(view.held, false);
    assert.equal(view.prediction, null);
    assert.equal(
      view.message,
      `${expected} 에러가 발생했습니다. 확인이 필요합니다.`,
    );
  });
}

test("processing failures show safe mapped messages rather than raw error details", () => {
  for (const reason of [
    "processing_lag",
    "queue_overflow",
    "timestamp_order",
    "private unknown exception",
  ]) {
    const view = predictionDisplay(
      receivePrediction(
        initial(),
        snapshot(
          { prediction_usable: false },
          {
            status: "invalid_input",
            reason,
          },
        ),
        at,
      ),
    );
    assert.equal(view.isError, true);
    assert.match(view.message, /에러가 발생했습니다\. 확인이 필요합니다\./);
    assert.doesNotMatch(view.message, /private/);
  }
});

test("session or model changes discard old forecasts, including during warmup", () => {
  for (const overrides of [
    { run_id: "run-two" },
    { model_version: "model-two" },
    { run_id: null },
  ]) {
    const state = receivePrediction(
      initial(),
      snapshot(
        { ...overrides, prediction_usable: false },
        {
          status: "not_ready",
        },
      ),
      at,
    );
    assert.equal(predictionDisplay(state).prediction, null);
  }
});

test("disabled prediction clears the cached result", () => {
  const view = predictionDisplay(
    receivePrediction(initial(), snapshot({ enabled: false }), at),
  );
  assert.equal(view.prediction, null);
  assert.equal(view.isError, false);
  assert.match(view.message, /꺼져/);
});

test("stale connection and current detected errors keep clearly historical results", () => {
  const stale = predictionDisplay(
    receivePrediction(initial(), snapshot({ stale: true }), at),
  );
  assert.equal(stale.prediction, null);
  assert.equal(stale.held, false);
  assert.match(stale.message, /수신 지연/);
  const ineligible = predictionDisplay(
    receivePrediction(
      initial(),
      snapshot(
        { prediction_usable: false },
        {
          evaluation_eligible: false,
        },
      ),
      at,
    ),
  );
  assert.equal(ineligible.prediction, null);
  assert.equal(ineligible.held, false);
  assert.equal(ineligible.message, "이상이 발생하였습니다.");
  assert.equal(ineligible.faulted, true);
});

test("invalid probabilities cannot replace a good result or be displayed on first load", () => {
  for (const value of [NaN, Infinity, -0.1, 1.1]) {
    const bad = snapshot({}, { error_probability: value });
    assert.equal(
      predictionDisplay(receivePrediction(initial(), bad, at)).prediction,
      null,
    );
    assert.equal(
      predictionDisplay(receivePrediction(emptyPredictionState(), bad, at))
        .prediction,
      null,
    );
  }
});

test("deadline overruns preserve the forecast with a specific error", () => {
  const view = predictionDisplay(
    receivePrediction(
      initial(),
      snapshot(
        { prediction_usable: false },
        {
          deadline_exceeded: true,
        },
      ),
      at,
    ),
  );
  assert.equal(view.held, false);
  assert.equal(view.prediction, null);
  assert.equal(view.isError, true);
  assert.match(view.message, /처리 시간 초과/);
});

test("legacy timestamps use result receipt time with the correct label", () => {
  const view = predictionDisplay(
    receivePrediction(
      emptyPredictionState(),
      snapshot(
        {},
        {
          reference_time: undefined,
        },
      ),
      at,
    ),
  );
  assert.equal(view.timestamp, at);
  assert.equal(view.timestampLabel, "마지막 결과 수신 시각");
});

test("a silent prediction query times out after ten seconds instead of appearing current for five minutes", async () => {
  const original = {
    fetch: globalThis.fetch,
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
  };
  let expire;
  globalThis.setTimeout = (callback, ms) => {
    assert.equal(ms, 10000);
    expire = callback;
    return 1;
  };
  globalThis.clearTimeout = () => {};
  globalThis.fetch = async (url, { signal }) => {
    assert.equal(url, "/api/ml/prediction");
    return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      );
    });
  };
  try {
    const pending = getMlPrediction();
    expire();
    await assert.rejects(pending, /응답 대기 시간이 초과/);
  } finally {
    Object.assign(globalThis, original);
  }
});

test("leaving the dashboard cancels its pending prediction query", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (_url, { signal }) =>
    new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      );
    });
  try {
    const controller = new AbortController();
    const pending = getMlPrediction(controller.signal);
    controller.abort();
    await assert.rejects(pending, { name: "AbortError" });
  } finally {
    globalThis.fetch = original;
  }
});

test("warmup shows the collecting message and 100% shows the error-found message", () => {
  const warmup = predictionDisplay(
    receivePrediction(
      emptyPredictionState(),
      snapshot({ prediction_usable: false }, { status: "not_ready" }),
      at,
    ),
  );
  assert.equal(warmup.message, "데이터를 수집하고 있습니다.");
  assert.equal(warmup.found, false);

  const full = predictionDisplay(
    receivePrediction(
      emptyPredictionState(),
      snapshot({}, { error_probability: 1 }),
      at,
    ),
  );
  assert.equal(full.message, "이상현상이 발견 되었습니다");
  assert.equal(full.found, true);
  assert.equal(full.prediction, null);
  assert.equal(predictionDisplay(initial()).found, false);
  const recovered = predictionDisplay(
    receivePrediction(
      receivePrediction(
        emptyPredictionState(),
        snapshot({}, { error_probability: 1 }),
        at,
      ),
      snapshot({}, { error_probability: 0.1 }),
      at,
    ),
  );
  assert.equal(recovered.found, false);
  assert.equal(recovered.message, "");
  assert.equal(recovered.prediction.error_probability, 0.1);
});
