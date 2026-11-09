// 초기 센서 시험 보고서 5건의 표시만 정리한다. 승인 원문과 출처 정보는 보존한다.
export function sensorFixtureText(text: string, incidentId?: string) {
  if (!/^INC-SENSOR-TEST-V1-M10-00[1-5]$/.test(incidentId ?? "")) return text;
  return text
    .replace(/\[가상\s*(?:시연|설정|현장\s*확인\s*설정|센서\s*시험)\]\s*/g, "")
    .replace(/\s*\(가상\s*설정\)/g, "");
}
