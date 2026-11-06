import { incidentCodeText } from "../ui/incidentCodes";

const fieldLabels: Record<string, string> = {
  infeed_present: "입구 감지",
  outfeed_present: "출구 감지",
  rpm: "회전속도",
  dc_input_current_a: "DC 입력 전류",
  dc_bus_voltage_v: "DC 버스 전압",
  motor_housing_temp_c: "모터 외함 온도",
  de_vibration_rms_g: "구동측 진동 RMS",
  de_kurtosis: "구동측 첨도",
  nde_vibration_rms_g: "반구동측 진동 RMS",
  nde_kurtosis: "반구동측 첨도",
};

const sensorUnits: Record<string, string> = {
  rpm: "r/min",
  dc_input_current_a: "A",
  dc_bus_voltage_v: "V",
  motor_housing_temp_c: "°C",
  de_vibration_rms_g: "g",
  nde_vibration_rms_g: "g",
  de_kurtosis: "",
  nde_kurtosis: "",
};

export function formatReportMeasurement(
  field: string,
  value: boolean | number | null | undefined,
  fallbackUnit = "",
) {
  if (typeof value === "boolean") return value ? "감지" : "미감지";
  if (typeof value !== "number" || !Number.isFinite(value)) return "미수집";
  const unit = sensorUnits[field] ?? fallbackUnit;
  const number = value.toFixed(2);
  return unit && unit !== "-" ? `${number} ${unit}` : number;
}

// 프로젝트에서 확정한 내부 설비명·모델명. 제조사 모델을 추정하지 않는다.
const equipment: Record<string, { name: string; model: string }> = {
  "BLDC-001": {
    name: "배터리 트레이 이송 컨베이어",
    model: "WW-BTC-001",
  },
};

// 설비 목록 API가 없어 프로젝트에서 확정한 설비만 이름을 돌려준다(없으면 빈 문자열).
export function reportEquipmentName(assetId?: string) {
  return assetId ? (equipment[assetId]?.name ?? "") : "";
}

export function knownEquipmentIds() {
  return Object.keys(equipment);
}

export function reportEquipmentLabel(assetId?: string, suppliedName = "") {
  const name = suppliedName.trim();
  if (name && name !== assetId) return name;
  const entry = assetId ? equipment[assetId] : undefined;
  return entry ? `${entry.name} / ${entry.model}` : name || assetId || "";
}

export function alarmDescriptions(
  incident: { codes?: string[] } | null,
  _analysis: { observed_facts?: string } | null,
) {
  // The display name is available before AI analysis and is not extracted from its prose.
  return (incident?.codes ?? []).map((code) => incidentCodeText(code));
}

export function measurementSummary(evidence: {
  field: string;
  valid?: boolean;
  value?: boolean | number | null;
  unit?: string;
  observed?: string;
  threshold?: string;
}) {
  const label = fieldLabels[evidence.field] ?? evidence.field;
  const valid =
    evidence.valid !== false &&
    evidence.value != null &&
    (typeof evidence.value === "boolean" || Number.isFinite(evidence.value));
  if (!valid) return `${label}: 유효한 측정값 없음`;

  const value = formatReportMeasurement(
    evidence.field,
    evidence.value,
    evidence.unit,
  );
  let threshold = evidence.threshold;
  if (threshold) {
    const match = threshold.match(
      /^A=\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\],\s*B\s*<=\s*(-?[\d.]+)\s*,\s*C\s*>=\s*(-?[\d.]+)\s*(.*?)\s*$/,
    );
    if (match && typeof evidence.value === "number") {
      const [, lower, upper, low, high, rawUnit] = match;
      const unit =
        rawUnit === "℃" || rawUnit === "°C"
          ? "℃"
          : rawUnit
            ? ` ${rawUnit}`
            : "";
      const relevant =
        evidence.value > Number(upper)
          ? `상한 이탈 시 경고 기준: ${high}${unit} 이상`
          : evidence.value < Number(lower)
            ? `하한 이탈 시 경고 기준: ${low}${unit} 이하`
            : `경고 기준: ${low}${unit} 이하 또는 ${high}${unit} 이상`;
      threshold = `정상 범위: ${lower}~${upper}${unit} · ${relevant}`;
    } else {
      const phrases: Record<string, string> = {
        "RUN 기동 3초 이후 rpm <1000":
          "운전 시작 3초 후 회전속도 1,000 rpm 미만",
        "기동 완료 후 rpm <=100 연속 3초":
          "기동 완료 후 회전속도 100 rpm 이하가 3초간 지속",
        "20초 21표본 max-min >30 Warning, >60 Error":
          "20초간 표본의 최대·최소 차이가 30 초과면 주의, 60 초과면 경고",
        "한쪽 비율 >1.25 Warning, >1.50 Error, 다른 쪽 <=1.10; 10초 지속":
          "한쪽 비율이 1.25 초과면 주의, 1.50 초과면 경고이며 다른 쪽은 1.10 이하인 상태가 10초 지속",
        "연속 true >3초 Warning, >5초 Error; false 2초 회복":
          "센서 감지가 3초 초과 지속되면 주의, 5초 초과면 경고 · 미감지 2초 지속 시 회복",
        "투입 4~6초, 최근 5간격 중 3회 이탈 Error":
          "최근 투입 간격 5회 중 3회가 4~6초 범위를 벗어나면 경고",
        "미투입 >6초 Warning, >10초 Error":
          "트레이 미투입이 6초 초과면 주의, 10초 초과면 경고",
        "출구 미도착 >16초": "트레이가 16초 넘게 출구에 도착하지 않음",
        "RUN·수신 가능·재공 존재·출구 이벤트 없음 >16초":
          "운전 중 수신 가능하고 트레이가 있는데 출구 감지가 16초 넘게 없음",
        "유효 이송 <14초 Warning, 60초 내 최근 5개 중 3회 Error":
          "이송시간 14초 미만이면 주의, 60초 내 최근 5회 중 3회면 경고",
        "비중첩 5개 창: median >15.5 또는 max-min >2초":
          "이송시간 5개의 중앙값이 15.5초 초과이거나 최대·최소 차이가 2초 초과",
      };
      threshold = phrases[threshold] ?? threshold;
    }
  }
  return [
    `${label}: ${value}`,
    evidence.observed,
    threshold
      ? threshold.startsWith("정상 범위:")
        ? threshold
        : `판정 기준: ${threshold}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
}
