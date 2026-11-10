const fields = {
  rpm: "모터 회전 속도",
  dc_input_current_a: "DC 입력 전류",
  dc_bus_voltage_v: "DC 버스 전압",
  motor_housing_temp_c: "모터 외함 온도",
  infeed_present: "입구 센서",
  outfeed_present: "출구 센서",
  de_vibration_rms_g: "구동측 진동 RMS",
  de_kurtosis: "구동측 첨도",
  nde_vibration_rms_g: "반구동측 진동 RMS",
  nde_kurtosis: "반구동측 첨도",
};
const statistics = {
  min: "최솟값",
  max: "최댓값",
  mean: "평균",
  first: "처음값",
  last: "마지막값",
  delta: "변화량",
  valid_count: "유효 표본 수",
  missing_count: "결측 수",
  true_count: "감지 표본 수",
  false_count: "미감지 표본 수",
};

export function humanizeAnalysisText(value) {
  if (typeof value !== "string") return value;
  return value
    .replace(/\bpriority_reason\b/g, "점검 순서의 근거")
    .replace(/\binspection_priority\b/g, "점검 우선순위")
    .replace(
      /\blikelihood\b(가|를|는|와)?/g,
      (_, particle) =>
        `원인 가능성${{ 가: "이", 를: "을", 는: "은", 와: "과" }[particle] || ""}`,
    )
    .replace(
      /\b(sensor_claims|sensor_claim_indices|offset_seconds|check_citations|action_citations|approval_citations|evidence_ids)\b/g,
      (word) =>
        ({
          sensor_claims: "검증용 센서 수치",
          sensor_claim_indices: "관련 센서 관측",
          offset_seconds: "사건 대비 조치 시간 차이(초)",
          check_citations: "점검 출처 연결",
          action_citations: "조치 출처 연결",
          approval_citations: "승인 필요 조치의 출처 연결",
          evidence_ids: "출처 정보",
        })[word],
    )
    .replace(
      /\b([a-z_]+)\.(min|max|mean|first|last|delta|valid_count|missing_count|true_count|false_count)\b/g,
      (whole, field, stat) =>
        fields[field] ? `${fields[field]} ${statistics[stat]}` : whole,
    )
    .replace(/\bwindow-(\d+)\b/g, "조회 구간 $1")
    .replace(/표본 None~None/g, "표본 없음");
}
