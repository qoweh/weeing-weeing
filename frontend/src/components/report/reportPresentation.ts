const fieldLabels: Record<string, string> = {
  infeed_present: '입구 감지',
  outfeed_present: '출구 감지',
  rpm: '회전속도',
  dc_input_current_a: 'DC 입력 전류',
  dc_bus_voltage_v: 'DC 버스 전압',
  motor_housing_temp_c: '모터 하우징 온도',
  de_vibration_rms_g: '구동측 진동 RMS',
  de_kurtosis: '구동측 첨도',
  nde_vibration_rms_g: '반구동측 진동 RMS',
  nde_kurtosis: '반구동측 첨도',
}

export function alarmDescriptions(
  incident: { codes?: string[] } | null,
  analysis: { observed_facts?: string } | null,
) {
  // describe()가 기록한 코드 표시명만 읽고 자유 서술·통계 본문은 표시하지 않는다.
  const codeLine =
    analysis?.observed_facts
      ?.split(/\r?\n/)
      .find((line) => line.startsWith('코드: ')) ?? ''
  const descriptions = new Map(
    [...codeLine.matchAll(/(BTT2-[PMD]\d{2})\(([^)\r\n]+)\)/g)].map((match) => [
      match[1],
      match[2],
    ]),
  )
  return (incident?.codes ?? []).map(
    (code) => `${code} — ${descriptions.get(code) || '설명 연결 대기'}`,
  )
}

export function measurementSummary(evidence: {
  field: string
  valid?: boolean
  value?: boolean | number | null
  unit?: string
  observed?: string
  threshold?: string
}) {
  const label = fieldLabels[evidence.field] ?? evidence.field
  const valid =
    evidence.valid !== false &&
    evidence.value != null &&
    (typeof evidence.value === 'boolean' || Number.isFinite(evidence.value))
  if (!valid) return `${label}: 유효한 측정값 없음`

  const value =
    typeof evidence.value === 'boolean'
      ? evidence.value
        ? '감지'
        : '미감지'
      : `${evidence.value}${evidence.unit ? ` ${evidence.unit}` : ''}`
  return [
    `${label}: ${value}`,
    evidence.observed,
    evidence.threshold ? `판정 기준: ${evidence.threshold}` : null,
  ]
    .filter(Boolean)
    .join(' · ')
}
