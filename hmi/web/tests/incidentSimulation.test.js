import test from 'node:test'
import assert from 'node:assert/strict'
import { simulateIncident, pollAnalysis } from '../src/pages/incidentSimulation.js'

globalThis.window = { location: { protocol: 'http:', host: 'localhost:5173' } }

class FakeSocket extends EventTarget {
  static ready = { status: 'connected', agent_status: 'connected' }
  static reply = () => ({ status: 'processed', db_status: 'saved', error_entries: [], incidents: [] })
  constructor(url) {
    super()
    this.url = url
    this.sent = []
    FakeSocket.instance = this
    queueMicrotask(() => this.message(FakeSocket.ready))
  }
  message(data) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(data) })) }
  send(data) {
    const record = JSON.parse(data)
    this.sent.push(record)
    queueMicrotask(() => this.message({ record_id: record.record_id, ...FakeSocket.reply(record) }))
  }
  close() { this.closed = true }
}
globalThis.WebSocket = FakeSocket

test('sends a complete frame and returns the actual detected error', async () => {
  const error = { incident_id: 'INC-1', codes: ['BTT2-M10'], severity: 'Error' }
  FakeSocket.ready = { status: 'connected', agent_status: 'connected' }
  FakeSocket.reply = () => ({ status: 'processed', db_status: 'saved', incidents: [error], error_entries: [error] })
  const changes = []
  const values = { infeed_present: false, outfeed_present: false, rpm: 1015, dc_input_current_a: 0.0918, dc_bus_voltage_v: 24, motor_housing_temp_c: 95, de_vibration_rms_g: 0.06, de_kurtosis: 5, nde_vibration_rms_g: 0.055, nde_kurtosis: 4.5 }
  const result = await simulateIncident({ values, duration: 20, signal: new AbortController().signal, onProgress() {}, onEvents: (items) => changes.push(...items) })
  assert.deepEqual(result, [error])
  assert.deepEqual(changes, [error])
  assert.equal(FakeSocket.instance.sent.length, 1)
  assert.equal(Object.keys(FakeSocket.instance.sent[0]).length, 15)
  assert.equal(FakeSocket.instance.sent[0].motor_housing_temp_c, 95)
  assert.match(FakeSocket.instance.url, /\/api\/ws\/telemetry\?context=MINIMAL$/)
  assert.equal(FakeSocket.instance.closed, true)
})

test('does not send samples when automatic analysis is disabled', async () => {
  FakeSocket.ready = { status: 'connected', agent_status: 'not_connected' }
  await assert.rejects(simulateIncident({ values: {}, duration: 1, signal: new AbortController().signal, onProgress() {}, onEvents() {} }), /자동 분석이 꺼져/)
  assert.equal(FakeSocket.instance.sent.length, 0)
  assert.equal(FakeSocket.instance.closed, true)
})

test('stops when persistence fails instead of starting result polling', async () => {
  FakeSocket.ready = { status: 'connected', agent_status: 'connected' }
  FakeSocket.reply = () => ({ status: 'processed', db_status: 'failed' })
  await assert.rejects(simulateIncident({ values: {}, duration: 1, signal: new AbortController().signal, onProgress() {}, onEvents() {} }), /저장하지 못했습니다/)
  assert.equal(FakeSocket.instance.sent.length, 1)
})

test('poll returns the analysis attached to the completed job', async () => {
  const result = { job: { status: 'COMPLETED' }, analysis: { status: 'OK' } }
  const updates = []
  await pollAnalysis('INC-1', async (id) => { assert.equal(id, 'INC-1'); return result }, new AbortController().signal, (item) => updates.push(item))
  assert.deepEqual(updates, [result])
})
