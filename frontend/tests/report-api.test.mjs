import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getIncidentReportContext } from '../src/api/client.js'
test('report context keeps the report identity in its request', async () => {
  const original = globalThis.fetch
  let requested
  globalThis.fetch = async (url) => {
    requested = url
    return new Response('{}', {
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await getIncidentReportContext('INC/1', 'RPT?1')
    assert.equal(
      requested,
      '/api/incidents/INC%2F1/report-context?report_id=RPT%3F1',
    )
  } finally {
    globalThis.fetch = original
  }
})
