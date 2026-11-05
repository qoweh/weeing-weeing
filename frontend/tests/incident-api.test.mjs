import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  deleteIncident,
  listIncidentApprovedReports,
  retryIncidentAnalysis,
  setAccessToken,
} from '../src/api/client.js'

test('incident actions use encoded IDs, session authentication and explicit retry identity', async () => {
  const original = globalThis.fetch
  const requests = []
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options })
    return new Response('{}', { headers: { 'Content-Type': 'application/json' } })
  }
  try {
    setAccessToken('fake-session')
    const body = { job_id: 'job-1', request_id: 'request-1' }
    await retryIncidentAnalysis('INC/1', body)
    await listIncidentApprovedReports('INC/1')
    await deleteIncident('INC/1')
    assert.equal(requests[0].url, '/api/incidents/INC%2F1/analysis/retry')
    assert.equal(requests[0].options.method, 'POST')
    assert.deepEqual(JSON.parse(requests[0].options.body), body)
    assert.equal(requests[0].options.headers.Authorization, 'Bearer fake-session')
    assert.equal(requests[1].url, '/api/incidents/INC%2F1/approved-reports')
    assert.equal(requests[2].url, '/api/incidents/INC%2F1')
    assert.equal(requests[2].options.method, 'DELETE')
  } finally {
    setAccessToken('')
    globalThis.fetch = original
  }
})
