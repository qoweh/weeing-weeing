import test from 'node:test'
import assert from 'node:assert/strict'
import { candidateBasis, displayIncidentFacts } from '../src/components/incidentFacts.js'

test('incident information uses the displayed number without altering its details', () => {
  const text = '사건:\n사건 ID: INC-abc\n설비: BAT-01 / BLDC-001\n코드: BTT2-M10'
  const incident = { incident_id: 'INC-abc', incident_number: 'INC-BTT2-M10-20261105-001' }
  assert.equal(displayIncidentFacts(text, incident), '사건번호: INC-BTT2-M10-20261105-001\n설비: BAT-01 / BLDC-001\n코드: BTT2-M10')
  assert.match(displayIncidentFacts(text, { incident_id: 'INC-abc' }), /^사건번호: 확인되지 않음\n/)
  assert.equal(displayIncidentFacts(text, { incident_id: 'INC-other' }), text)
  assert.equal(displayIncidentFacts('사건: 사람이 작성한 설명', incident), '사건: 사람이 작성한 설명')
})

test('candidate descriptions omit only duplicated common facts and retain distinct explanations', () => {
  const common = '사건:\n사건 ID: INC-abc\n센서: 온도 95℃'
  assert.equal(candidateBasis(common, common), '')
  assert.equal(candidateBasis(common.replace(/\n/g, '\r\n') + '\n', common), '')
  const distinct = `${common}\n냉각 상태는 현장 점검으로 확인해야 한다.`
  assert.equal(candidateBasis(distinct, common), distinct)
  assert.equal(candidateBasis('팬 작동 상태 확인 필요', common), '팬 작동 상태 확인 필요')
  assert.equal(candidateBasis(common, ''), common)
})
