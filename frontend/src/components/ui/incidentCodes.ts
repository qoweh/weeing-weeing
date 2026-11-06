// Display-only vocabulary. Detector/DB identifiers and historical text remain unchanged.
const definitions = {
  "BTT2-P01": ["이송 시간 초과", "이송시간 초과"],
  "BTT2-P02": ["이송 시간 단축", "빠른 이송"],
  "BTT2-P03": ["입구 장시간 점유", "입구 장기 점유"],
  "BTT2-P04": ["출구 장시간 점유", "출구 장기 점유"],
  "BTT2-P05": ["투입 주기 이상", "투입 주기 이탈"],
  "BTT2-P06": ["출구 감지 없음", "출구 이벤트 없음"],
  "BTT2-P07": ["이송 시간 증가·불안정", "이송시간 증가·불안정"],
  "BTT2-M01": ["모터 기동 실패·운전 중 정지", "기동 미도달·운전 중 정지"],
  "BTT2-M02": ["모터 속도 저하", "RPM 하한 이탈"],
  "BTT2-M03": ["모터 속도 상승", "RPM 상한 이탈"],
  "BTT2-M04": ["모터 속도 변동", "RPM 변동"],
  "BTT2-M05": ["모터 입력 전류 저하", "DC 입력전류 하한 이탈"],
  "BTT2-M06": ["모터 입력 전류 상승", "DC 입력전류 상한 이탈"],
  "BTT2-M07": ["DC 버스 전압 저하", "DC 버스전압 하한 이탈"],
  "BTT2-M08": ["DC 버스 전압 상승", "DC 버스전압 상한 이탈"],
  "BTT2-M09": ["모터 온도 저하", "외함 온도 하한 이탈"],
  "BTT2-M10": ["모터 온도 상승", "외함 온도 상한 이탈"],
  "BTT2-M11": ["구동측 진동 저하", "DE 진동 RMS 하한 이탈"],
  "BTT2-M12": ["구동측 진동 상승", "DE 진동 RMS 상한 이탈"],
  "BTT2-M13": ["구동측 진동 첨도 저하", "DE 첨도 하한 이탈"],
  "BTT2-M14": ["구동측 진동 첨도 상승", "DE 첨도 상한 이탈"],
  "BTT2-M15": ["반구동측 진동 저하", "NDE 진동 RMS 하한 이탈"],
  "BTT2-M16": ["반구동측 진동 상승", "NDE 진동 RMS 상한 이탈"],
  "BTT2-M17": ["반구동측 진동 첨도 저하", "NDE 첨도 하한 이탈"],
  "BTT2-M18": ["반구동측 진동 첨도 상승", "NDE 첨도 상한 이탈"],
  "BTT2-M19": ["한쪽 진동 상대 증가", "특정 측 진동 상대 변화"],
  "BTT2-D01": ["데이터 형식·식별 오류", "형식·식별 오류"],
  "BTT2-D02": ["필수 센서값 누락·무효", "필수값 미확보"],
  "BTT2-D03": ["데이터 시각·수신 이상", "시간·신선도 오류"],
  "BTT2-D04": ["트레이 추적 신뢰도 저하", "추적 신뢰성 부족"],
  "BTT2-D05": ["운전 설정·상태 정보 부족", "설정·문맥 미확보"],
} as const;

export const registeredIncidentCodes = Object.keys(definitions);

function definition(code: string) {
  return Object.hasOwn(definitions, code)
    ? definitions[code as keyof typeof definitions]
    : undefined;
}

export function incidentCodeName(code: string, prediction = false) {
  const name = definition(code)?.[0] ?? "미등록 코드";
  return prediction ? `${name} 가능성` : name;
}

export function incidentCodeText(code: string, prediction = false) {
  return `${incidentCodeName(code, prediction)} (${code})`;
}

export function incidentCodesText(codes: readonly string[] = []) {
  return codes.map((code) => incidentCodeText(code)).join(", ");
}

export function incidentCodeMatches(codes: readonly string[], query: string) {
  const normalize = (value: string) =>
    value.normalize("NFC").toLowerCase().replace(/\s+/g, "");
  const term = normalize(query);
  return codes.some((code) =>
    normalize([code, ...(definition(code) ?? [])].join(" ")).includes(term),
  );
}

export function incidentCodeDetail(code: string) {
  const official = definition(code)?.[1];
  if (!official) return "표시명이 등록되지 않은 코드입니다.";
  const detail = ["BTT2-M09", "BTT2-M10"].includes(code)
    ? "모터 외함 온도 측정값 기준입니다."
    : ["BTT2-M11", "BTT2-M12", "BTT2-M15", "BTT2-M16"].includes(code)
      ? "진동 실효값(RMS) 측정값 기준입니다."
      : ["BTT2-M13", "BTT2-M14", "BTT2-M17", "BTT2-M18"].includes(code)
        ? "첨도는 진동 파형의 뾰족한 정도를 나타내는 지표입니다."
        : "";
  return `공식 명칭: ${official}${detail ? ` · ${detail}` : ""}`;
}
