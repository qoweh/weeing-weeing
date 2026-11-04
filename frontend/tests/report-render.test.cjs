const { test } = require('node:test')
const assert = require('node:assert/strict')
const render = require('./helpers/render-report.cjs')
const incident = {
  incident_id: 'INC-M08',
  process_id: 'P1',
  asset_id: 'A1',
  codes: ['BTT2-M08'],
  first_detected_at: '2026-11-03T02:08:22Z',
  last_detected_at: '2026-11-03T02:09:23Z',
  evidence: [{ field: 'dc_bus_voltage_v', value: 25.158, unit: 'V' }],
}
const analysis = {
  incident_id: 'INC-M08',
  status: 'OK',
  observed_facts: '코드: BTT2-M08(DC 버스전압 상한 이탈)',
  suspected_causes: [
    {
      cause: '전원 설정 확인',
      basis: 'RAW_BASIS_MUST_NOT_APPEAR',
      evidence_ids: ['MANUAL:1'],
    },
  ],
  recommended_checks: ['전원 확인', '계측 확인'],
  recommended_actions: ['매뉴얼 검토'],
  actions_requiring_approval: ['재가동 승인'],
  evidence: [{ citation: '매뉴얼', evidence_id: 'MANUAL:1' }],
}
const telemetry = {
  record_id: 'error-frame',
  timestamp: '2026-11-03T02:08:48Z',
  process_id: 'P1',
  asset_id: 'A1',
  dc_bus_voltage_v: 27.603,
  rpm: 0,
  infeed_present: false,
  outfeed_present: true,
  dc_input_current_a: null,
}
const props = {
  incident,
  analysis,
  analysisInput: {
    ...incident,
    evidence: [{ field: 'dc_bus_voltage_v', value: 27.603, unit: 'V' }],
  },
  telemetry,
  readOnly: true,
}

test('real report renders DB values including zero and false, not recovered evidence', () => {
  const html = render(props)
  assert.match(html, /27\.60 V/)
  assert.doesNotMatch(html, /27\.603/)
  assert.doesNotMatch(html, /25\.158/)
  assert.match(html, /회전속도 r\/min<\/strong><span>0\.00 r\/min<\/span>/)
  assert.match(html, /입구 감지<\/strong><span>미감지<\/span>/)
  assert.match(html, /DC 입력 전류 A<\/strong><span>미수집<\/span>/)
  assert.match(html, /최초 감지/)
  assert.match(html, /마지막 감지/)
  assert.match(html, /측정값 표본 시각/)
})

test('report measurements round to two decimals with units without changing source data', () => {
  const measured = {
    ...telemetry,
    rpm: 1016.8668088500559,
    dc_input_current_a: 0.09235985127711276,
    dc_bus_voltage_v: 27.595783999562265,
    motor_housing_temp_c: 66.22531293346422,
    de_vibration_rms_g: 0.05858435447607954,
    de_kurtosis: 4.708336809911458,
    nde_vibration_rms_g: 0.05632581003116335,
    nde_kurtosis: 3.824811270607266,
  }
  const html = render({
    ...props,
    telemetry: measured,
    analysisInput: {
      ...incident,
      evidence: [
        {
          field: 'dc_bus_voltage_v',
          value: measured.dc_bus_voltage_v,
          unit: 'V',
        },
      ],
    },
  })
  for (const text of [
    '1016.87 r/min',
    '0.09 A',
    '27.60 V',
    '66.23 °C',
    '0.06 g',
    '4.71',
    '3.82',
  ])
    assert.ok(html.includes(text), text)
  assert.match(html, /DC 버스 전압: 27\.60 V/)
  assert.match(html, /입구 감지<\/strong><span>미감지<\/span>/)
  assert.match(html, /출구 감지<\/strong><span>감지<\/span>/)
  assert.doesNotMatch(html, /1016\.8668088500559|27\.595783999562265/)
  assert.equal(measured.rpm, 1016.8668088500559)
})
test('causes hide repeated basis; checks, actions, approval and citations have separate lists', () => {
  const html = render(props)
  assert.doesNotMatch(html, /RAW_BASIS_MUST_NOT_APPEAR/)
  assert.match(html, /설비: P1 \/ A1/)
  assert.match(html, /근거 ID: MANUAL:1/)
  assert.match(html, /<ol class="report-analysis-list"><li>전원 확인/)
  for (const text of ['권고 조치', '승인이 필요한 조치', '참조 매뉴얼·이력'])
    assert.ok(html.includes(text))
})
test('a different asset or incident cannot supply sensor values or AI text', () => {
  const html = render({
    ...props,
    telemetry: { ...telemetry, asset_id: 'OTHER', rpm: 9999 },
    analysis: { ...analysis, incident_id: 'OTHER' },
  })
  assert.doesNotMatch(html, /9999|전원 설정 확인/)
  assert.match(html, /AI 초안이 아직 연결되지 않았습니다/)
})

test('BLDC-001 reports automatically show the confirmed internal equipment name and model', () => {
  const html = render({ incident: { ...incident, asset_id: 'BLDC-001' } })
  assert.match(html, /배터리 트레이 이송 컨베이어 \/ WW-BTC-001/)
  assert.match(html, /P1 \/ BLDC-001/)
})

test('another asset never receives the BLDC equipment name; supplied names are preserved', () => {
  const unknown = render({ incident })
  assert.doesNotMatch(unknown, /WW-BTC-001|배터리 트레이 이송 컨베이어/)
  const supplied = render({
    incident: { ...incident, asset_id: 'BLDC-001' },
    assetName: '등록된 설비명 / 등록된 모델',
  })
  assert.match(supplied, /등록된 설비명 \/ 등록된 모델/)
  assert.doesNotMatch(supplied, /WW-BTC-001/)
})
