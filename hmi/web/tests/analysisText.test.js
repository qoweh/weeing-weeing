import test from 'node:test'
import assert from 'node:assert/strict'
import { humanizeAnalysisText } from '../src/components/analysisWording.js'

test('analysis terminology is readable while numeric values and evidence IDs remain intact', () => {
  const text = 'likelihood는 미평가. sensor_claims: window-1 motor_housing_temp_c.max=95.0℃. offset_seconds=-135.0. BTT-MANUAL:2.0:0010'
  const result = humanizeAnalysisText(text)
  assert.match(result, /원인 가능성은 미평가/)
  assert.match(result, /모터 외함 온도 최댓값=95\.0℃/)
  assert.match(result, /시간 차이\(초\)=-135\.0/)
  assert.match(result, /BTT-MANUAL:2\.0:0010/)
  assert.equal(humanizeAnalysisText(null), null)
  assert.equal(humanizeAnalysisText('관련 문서 2쪽 참조'), '관련 문서 2쪽 참조')
})
