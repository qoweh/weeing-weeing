export type TelemetryRecord = {
  record_id: string;
  timestamp: string;
  [field: string]: unknown;
};

export type TelemetrySnapshot = {
  epoch: string;
  run_id: string | null;
  sequence: number;
  producer_connected: boolean;
  stale: boolean;
  age_seconds: number | null;
  received_at: string | null;
  context_preset: string;
  db_status: string;
  agent_status: string;
  telemetry: TelemetryRecord | null;
  incidents: {
    incident_id: string;
    codes: string[];
    asset_id: string;
    first_detected_at: string;
    severity: string;
    status: string;
  }[];
};

export function parseTelemetrySnapshot(value: unknown): TelemetrySnapshot {
  const state = value as TelemetrySnapshot | null;
  if (
    !state ||
    typeof state !== "object" ||
    typeof state.epoch !== "string" ||
    !state.epoch ||
    !(state.run_id === null || typeof state.run_id === "string") ||
    !Number.isSafeInteger(state.sequence) ||
    state.sequence < 0 ||
    typeof state.producer_connected !== "boolean" ||
    typeof state.stale !== "boolean" ||
    !(
      state.age_seconds === null ||
      (typeof state.age_seconds === "number" &&
        Number.isFinite(state.age_seconds) &&
        state.age_seconds >= 0)
    ) ||
    !(
      state.received_at === null ||
      (typeof state.received_at === "string" &&
        Number.isFinite(Date.parse(state.received_at)))
    ) ||
    typeof state.context_preset !== "string" ||
    typeof state.db_status !== "string" ||
    typeof state.agent_status !== "string" ||
    !Array.isArray(state.incidents)
  )
    throw new Error("센서 상태 응답 형식이 올바르지 않습니다.");
  if (
    state.telemetry !== null &&
    (typeof state.telemetry !== "object" ||
      typeof state.telemetry.record_id !== "string" ||
      typeof state.telemetry.timestamp !== "string" ||
      !Number.isFinite(Date.parse(state.telemetry.timestamp)))
  )
    throw new Error("센서 표본 응답 형식이 올바르지 않습니다.");
  for (const incident of state.incidents) {
    if (
      !incident ||
      typeof incident.incident_id !== "string" ||
      !Array.isArray(incident.codes) ||
      !incident.codes.every((code) => typeof code === "string") ||
      typeof incident.asset_id !== "string" ||
      typeof incident.first_detected_at !== "string" ||
      typeof incident.severity !== "string" ||
      typeof incident.status !== "string"
    ) {
      throw new Error("센서 사건 응답 형식이 올바르지 않습니다.");
    }
  }
  return state;
}

export async function readTelemetryStream(
  response: Response,
  signal: AbortSignal,
  onSnapshot: (state: TelemetrySnapshot) => void,
  onActivity: () => void = () => {},
) {
  if (
    !response.body ||
    response.headers.get("content-type")?.split(";")[0].trim() !==
      "text/event-stream"
  ) {
    await response.body?.cancel().catch(() => {});
    throw new Error("센서 실시간 응답 형식이 올바르지 않습니다.");
  }
  const reader = response.body.getReader();
  const cancel = () => {
    void reader.cancel().catch(() => {});
  };
  signal.addEventListener("abort", cancel, { once: true });
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  try {
    while (true) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      const { value, done } = await reader.read();
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (done) throw new Error("센서 실시간 연결이 종료됐습니다.");
      onActivity();
      buffer += decoder.decode(value, { stream: true });
      let boundary: RegExpExecArray | null;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        if (signal.aborted) throw new DOMException("Aborted", "AbortError");
        const frame = buffer.slice(0, boundary.index).replace(/\r\n/g, "\n");
        buffer = buffer.slice(boundary.index + boundary[0].length);
        if (frame.length > 1_000_000)
          throw new Error("센서 이벤트가 너무 큽니다.");
        const lines = frame.split("\n");
        const data = lines
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).replace(/^ /, ""))
          .join("\n");
        if (!data) continue;
        const event = JSON.parse(data);
        const named = lines
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        if (!event || (named && named !== event.event))
          throw new Error("센서 이벤트 형식이 올바르지 않습니다.");
        if (event.event === "error") {
          if (
            !Number.isInteger(event.status_code) ||
            event.status_code < 400 ||
            event.status_code > 599
          ) {
            throw new Error("센서 인증 응답 형식이 올바르지 않습니다.");
          }
          const error = new Error(
            "센서 실시간 조회 인증 또는 서버 상태를 확인하세요.",
          ) as Error & { status: number };
          error.status = event.status_code;
          throw error;
        }
        if (event.event === "snapshot")
          onSnapshot(parseTelemetrySnapshot(event.state));
      }
      if (buffer.length > 1_000_000)
        throw new Error("센서 이벤트가 너무 큽니다.");
    }
  } finally {
    signal.removeEventListener("abort", cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
