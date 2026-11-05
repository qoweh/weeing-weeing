import type { TelemetryRecord, TelemetrySnapshot } from "../api/telemetry";

export const sensorCharts = [
  { title: "회전 속도", field: "rpm", code: "M02/M04", unit: "rpm", digits: 1 },
  {
    title: "DC 입력 전류",
    field: "dc_input_current_a",
    code: "M06",
    unit: "A",
    digits: 4,
  },
  {
    title: "DC 버스 전압",
    field: "dc_bus_voltage_v",
    code: "M07/M08",
    unit: "V",
    digits: 3,
  },
  {
    title: "모터 외함 온도",
    field: "motor_housing_temp_c",
    code: "M10",
    unit: "℃",
    digits: 2,
  },
  {
    title: "구동측 진동 RMS",
    field: "de_vibration_rms_g",
    code: "M12",
    unit: "g",
    digits: 5,
  },
  {
    title: "구동측 진동 첨도",
    field: "de_kurtosis",
    code: "M14",
    unit: "",
    digits: 4,
  },
  {
    title: "반구동측 진동 RMS",
    field: "nde_vibration_rms_g",
    code: "M16",
    unit: "g",
    digits: 5,
  },
  {
    title: "반구동측 진동 첨도",
    field: "nde_kurtosis",
    code: "M18",
    unit: "",
    digits: 4,
  },
] as const;

export type SensorSample = { time: number; record: TelemetryRecord };
export type ChartModel = {
  snapshot: TelemetrySnapshot | null;
  samples: SensorSample[];
  receivedAt: number;
  sessionChanged: boolean;
};

export function emptyChartModel(): ChartModel {
  return { snapshot: null, samples: [], receivedAt: 0, sessionChanged: false };
}

export function applySnapshot(
  model: ChartModel,
  snapshot: TelemetrySnapshot,
  now: number,
): ChartModel {
  const previous = model.snapshot;
  const changed =
    previous !== null &&
    (previous.epoch !== snapshot.epoch || previous.run_id !== snapshot.run_id);
  if (!changed && previous && snapshot.sequence < previous.sequence)
    return model;
  let samples = changed ? [] : model.samples;
  const record = snapshot.telemetry;
  const last = samples.at(-1);
  if (
    record &&
    (!last ||
      (last.record.record_id !== record.record_id &&
        Date.parse(record.timestamp) > last.time))
  ) {
    const time = Date.parse(record.timestamp);
    samples = [
      ...samples.filter((sample) => sample.time >= time - 60_000),
      { time, record },
    ].slice(-240);
  }
  return {
    snapshot,
    samples,
    receivedAt: now,
    sessionChanged: changed || (!changed && model.sessionChanged),
  };
}

export function sensorValue(
  record: TelemetryRecord | null | undefined,
  field: string,
): number | null {
  const value = record?.[field];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatSensor(value: number | null, digits: number): string {
  return value === null
    ? "—"
    : value.toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

export function sensorStatus(
  model: ChartModel,
  error: string | null,
  now: number,
) {
  if (error) return { label: "조회 연결 끊김 · 재연결 중", current: false };
  const state = model.snapshot;
  if (!state) return { label: "센서 연결 확인 중", current: false };
  if (!state.producer_connected)
    return { label: "송신 연결 없음", current: false };
  const age = state.age_seconds;
  if (
    state.stale ||
    age === null ||
    age + Math.max(0, now - model.receivedAt) / 1000 > 3
  ) {
    return { label: "수신 지연·대기", current: false };
  }
  return { label: "수신 중", current: true };
}

export function sensorPath(samples: SensorSample[], field: string): string {
  if (!samples.length) return "";
  const end = samples.at(-1)!.time;
  const visible = samples.filter((sample) => sample.time >= end - 60_000);
  const values = visible
    .map((sample) => sensorValue(sample.record, field))
    .filter((value): value is number => value !== null);
  if (!values.length) return "";
  const low = Math.min(...values);
  const high = Math.max(...values);
  const padding = Math.max((high - low) * 0.1, Math.abs(high) * 0.01, 0.00001);
  let previousTime: number | null = null;
  return visible
    .map((sample) => {
      const value = sensorValue(sample.record, field);
      if (value === null) {
        previousTime = null;
        return "";
      }
      const x = (sample.time - end + 60_000) / 100;
      const y =
        72 - ((value - low + padding) / (high - low + 2 * padding)) * 64;
      const command =
        previousTime === null || sample.time - previousTime > 2000 ? "M" : "L";
      previousTime = sample.time;
      return `${command}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

export function detectionLabel(
  record: TelemetryRecord | null | undefined,
  field: string,
) {
  const value = record?.[field];
  return value === true ? "감지" : value === false ? "미감지" : "미수신";
}
