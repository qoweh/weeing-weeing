import { test } from 'node:test'
import assert from 'node:assert/strict'
import { pollAnalysis } from '../src/incident-hmi/components/pollAnalysis.js'

test('completed analysis is delivered once without starting a new analysis', async () => {
  const controller = new AbortController()
  const updates = []
  const calls = []
  await pollAnalysis('INC-1', async (id) => {
    calls.push(id)
    return { job: { status: 'COMPLETED' } }
  }, controller.signal, (result) => updates.push(result))
  assert.deepEqual(calls, ['INC-1'])
  assert.equal(updates[0].job.status, 'COMPLETED')
})

test('closing the dialog ignores a response that arrives after cancellation', async () => {
  const controller = new AbortController()
  let resolve
  const pending = new Promise((done) => { resolve = done })
  const updates = []
  const running = pollAnalysis('INC-1', () => pending, controller.signal, (result) => updates.push(result))
  controller.abort()
  resolve({ job: { status: 'COMPLETED' } })
  await assert.rejects(running, { name: 'AbortError' })
  assert.deepEqual(updates, [])
})
