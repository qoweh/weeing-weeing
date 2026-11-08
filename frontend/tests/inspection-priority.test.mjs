import test from 'node:test'
import assert from 'node:assert/strict'
import { inspectionPriorityLabel } from '../src/incident-hmi/components/inspectionPriority.js'
import { inspectionPriorityLabel as legacyHmiLabel } from '../../hmi/web/src/components/inspectionPriority.js'

for (const [name, label] of [['frontend', inspectionPriorityLabel], ['hmi', legacyHmiLabel]]) {
  test(`${name}: priority is explicit and never inferred from an old likelihood`, () => {
    assert.equal(label({ inspection_priority: '우선 확인' }), '우선 확인')
    assert.equal(label({ inspection_priority: '후속 확인', likelihood: '상' }), '후속 확인')
    for (const likelihood of ['상', '중', '하', '미평가', null]) {
      assert.equal(label({ likelihood }), '점검 우선순위 미지정')
    }
    assert.equal(label({ inspection_priority: '상' }), '점검 우선순위 미지정')
  })
}
