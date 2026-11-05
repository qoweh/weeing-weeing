import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseTelemetrySnapshot,
  readTelemetryStream,
} from "../src/api/telemetry.ts";
import {
  getLatestTelemetry,
  setAccessToken,
  watchTelemetry,
} from "../src/api/client.js";
import {
  applySnapshot,
  emptyChartModel,
  sensorValue,
  sensorPath,
  sensorStatus,
  detectionLabel,
  formatSensor,
  sensorCharts,
} from "../src/views/telemetryCharts.ts";

function state(sequence = 1, time = 0, recordId = `fake-${sequence}`) {
  return {
    epoch: "fake-epoch",
    run_id: "fake-run",
    sequence,
    producer_connected: true,
    stale: false,
    age_seconds: 0,
    received_at: "2026-11-04T00:00:00Z",
    context_preset: "운전 가정",
    db_status: "saved",
    agent_status: "not_connected",
    incidents: [],
    telemetry: {
      record_id: recordId,
      timestamp: new Date(1793750400000 + time).toISOString(),
      rpm: 0,
      infeed_present: false,
    },
  };
}
const frame = (value) =>
  `event: snapshot\r\ndata: ${JSON.stringify({ event: "snapshot", state: value })}\r\n\r\n`;
function response(
  chunks,
  {
    close = true,
    cancelled = () => {},
    contentType = "text/event-stream",
  } = {},
) {
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks)
          controller.enqueue(
            typeof chunk === "string" ? new TextEncoder().encode(chunk) : chunk,
          );
        if (close) controller.close();
      },
      cancel: cancelled,
    }),
    { headers: { "Content-Type": contentType } },
  );
}

test("chart fields map to all eight real numeric sensors", () => {
  assert.deepEqual(
    sensorCharts.map((chart) => chart.field),
    [
      "rpm",
      "dc_input_current_a",
      "dc_bus_voltage_v",
      "motor_housing_temp_c",
      "de_vibration_rms_g",
      "de_kurtosis",
      "nde_vibration_rms_g",
      "nde_kurtosis",
    ],
  );
});
test("zero and false are valid; missing and invalid numeric readings are not converted to zero", () => {
  const record = state().telemetry;
  assert.equal(formatSensor(sensorValue(record, "rpm"), 1), "0");
  assert.equal(sensorValue(record, "dc_input_current_a"), null);
  assert.equal(sensorValue({ ...record, rpm: NaN }, "rpm"), null);
  assert.equal(sensorValue({ ...record, rpm: "42" }, "rpm"), null);
  assert.equal(formatSensor(null, 3), "—");
  assert.equal(detectionLabel(record, "infeed_present"), "미감지");
  assert.equal(detectionLabel(record, "outfeed_present"), "미수신");
});
test("repeated SSE snapshots update liveness but do not invent duplicate samples", () => {
  let model = applySnapshot(emptyChartModel(), state(), 1000);
  model = applySnapshot(
    model,
    { ...state(), stale: true, age_seconds: 4 },
    2000,
  );
  assert.equal(model.samples.length, 1);
  assert.equal(sensorStatus(model, null, 2000).current, false);
});
test("history ignores older sequence responses and is bounded by time and count", () => {
  let model = emptyChartModel();
  for (let n = 1; n <= 500; n++)
    model = applySnapshot(model, state(n, n * 100), n);
  assert.equal(model.samples.length, 240);
  assert.equal(applySnapshot(model, state(1), 1000), model);
  model = applySnapshot(model, state(501, 120000), 1001);
  assert.equal(model.samples.length, 1);
});
for (const field of ["epoch", "run_id"]) {
  test(`a new ${field} clears old plots, including an initially empty new session`, () => {
    const old = applySnapshot(emptyChartModel(), state(), 1);
    const next = {
      ...state(0),
      [field]: "new-session",
      telemetry: null,
      age_seconds: null,
      stale: true,
    };
    const model = applySnapshot(old, next, 2);
    assert.equal(model.samples.length, 0);
    assert.equal(model.snapshot.telemetry, null);
    assert.equal(model.sessionChanged, true);
  });
}
test("stale, disconnected, aged and network-error values never remain current", () => {
  const model = applySnapshot(emptyChartModel(), state(), 1000);
  assert.equal(sensorStatus(model, null, 1000).current, true);
  assert.equal(sensorStatus(model, null, 4001).current, false);
  assert.equal(sensorStatus(model, "network error", 1001).current, false);
  const disconnected = applySnapshot(
    model,
    { ...state(2), producer_connected: false },
    1001,
  );
  assert.equal(sensorStatus(disconnected, null, 1001).label, "송신 연결 없음");
});
test("plot paths break at missing data and gaps, with no NaN or fake line through an outage", () => {
  const samples = [0, 500, 1000, 1500, 5000].map((time, index) => ({
    time,
    record: {
      ...state(index, time).telemetry,
      rpm: index === 2 ? null : index,
    },
  }));
  const path = sensorPath(samples, "rpm");
  assert.equal((path.match(/M/g) || []).length, 3);
  assert.equal((path.match(/L/g) || []).length, 1);
  assert.doesNotMatch(path, /NaN|Infinity/);
  assert.equal(sensorPath(samples, "missing"), "");
});
test("REST/SSE snapshots reject malformed state rather than showing it as healthy", () => {
  for (const invalid of [
    null,
    {},
    { ...state(), sequence: -1 },
    { ...state(), age_seconds: "0" },
    { ...state(), telemetry: {} },
    { ...state(), incidents: [{}] },
  ]) {
    assert.throws(() => parseTelemetrySnapshot(invalid));
  }
  assert.deepEqual(parseTelemetrySnapshot(state()), state());
});
test("SSE parses UTF-8 and CRLF split across arbitrary network chunks", async () => {
  const controller = new AbortController();
  const bytes = new TextEncoder().encode(
    ": heartbeat\r\n\r\n" + frame(state()),
  );
  const chunks = Array.from(bytes, (byte) => Uint8Array.of(byte));
  const received = [];
  const stream = response(chunks, { close: false });
  await assert.rejects(
    readTelemetryStream(stream, controller.signal, (value) => {
      received.push(value);
      controller.abort();
    }),
    { name: "AbortError" },
  );
  assert.deepEqual(received, [state()]);
});
test("abort stops buffered snapshots and cancels a pending stream", async () => {
  const controller = new AbortController();
  let cancelled = false;
  let count = 0;
  await assert.rejects(
    readTelemetryStream(
      response([frame(state()) + frame(state(2))], {
        close: false,
        cancelled: () => {
          cancelled = true;
        },
      }),
      controller.signal,
      () => {
        count++;
        controller.abort();
      },
    ),
    { name: "AbortError" },
  );
  assert.equal(count, 1);
  assert.equal(cancelled, true);
});
test("unexpected SSE EOF is an error so subscribers can reconnect", async () => {
  const values = [];
  await assert.rejects(
    readTelemetryStream(
      response([frame(state())]),
      new AbortController().signal,
      (value) => values.push(value),
    ),
    /종료/,
  );
  assert.equal(values.length, 1);
});
test("SSE auth errors preserve status without exposing the server response body", async () => {
  await assert.rejects(
    readTelemetryStream(
      response([
        'event: error\ndata: {"event":"error","status_code":401,"message":"PRIVATE_RESPONSE"}\n\n',
      ]),
      new AbortController().signal,
      () => {},
    ),
    (error) => {
      assert.equal(error.status, 401);
      assert.doesNotMatch(error.message, /PRIVATE_RESPONSE/);
      return true;
    },
  );
});
test("SSE validates content type and limits complete as well as partial events", async () => {
  await assert.rejects(
    readTelemetryStream(
      response(["{}"], { contentType: "application/json" }),
      new AbortController().signal,
      () => {},
    ),
    /형식/,
  );
  for (const body of [
    "data: " + "x".repeat(1000001),
    "data: " + "x".repeat(1000001) + "\n\n",
  ]) {
    await assert.rejects(
      readTelemetryStream(
        response([body]),
        new AbortController().signal,
        () => {},
      ),
      /너무/,
    );
  }
});
test("bootstrap REST uses the existing Bearer session and no producer token or URL credentials", async () => {
  const original = globalThis.fetch;
  setAccessToken("fake-session-only");
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/telemetry/latest");
    assert.equal(options.headers.Authorization, "Bearer fake-session-only");
    return new Response(JSON.stringify(state()), {
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    assert.deepEqual(
      await getLatestTelemetry(new AbortController().signal),
      state(),
    );
  } finally {
    globalThis.fetch = original;
    setAccessToken("");
  }
});
test("silent SSE fetch is aborted by the watchdog instead of hanging indefinitely", async () => {
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
  globalThis.fetch = async (_url, { signal }) =>
    new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      );
    });
  try {
    const pending = watchTelemetry(new AbortController().signal, () => {});
    expire();
    await assert.rejects(pending, { name: "AbortError" });
  } finally {
    Object.assign(globalThis, original);
  }
});
