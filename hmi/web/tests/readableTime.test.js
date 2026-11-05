import test from 'node:test'
import assert from 'node:assert/strict'
import { formatReadableTime, formatTimesInText } from '../src/components/readableTime.js'

test('UTC and offset timestamps show Korea time without fractional seconds', () => {
  const first = formatReadableTime('2026-11-04T01:34:01.234567Z')
  assert.match(first, /2026\. 11\. 04/)
  assert.match(first, /10:34:01/)
  assert.doesNotMatch(first, /한국 시간/)
  assert.equal(formatReadableTime('2026-11-04T10:34:01+09:00'), first)
})

test('timestamps embedded in analysis text are converted while other text stays intact', () => {
  const result = formatTimesInText('발생 2026-11-04T01:34:01.234Z / BTT2-M10')
  assert.match(result, /10:34:01/)
  assert.match(result, /BTT2-M10/)
  assert.doesNotMatch(result, /\.234Z/)
  assert.equal(formatReadableTime('not-a-date'), 'not-a-date')
})
