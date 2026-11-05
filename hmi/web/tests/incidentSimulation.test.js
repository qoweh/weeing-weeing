import test from 'node:test'
import assert from 'node:assert/strict'
import { simulateIncident, pollAnalysis, runDashboardSimulation } from '../src/pages/incidentSimulation.js'

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
  const url = new URL(FakeSocket.instance.url)
  assert.equal(url.searchParams.get('context'), 'MINIMAL')
  assert.equal(url.searchParams.get('origin'), 'SIMULATION')
  assert.equal(url.searchParams.get('interval_s'), '1')
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


test('dashboard sends normal, error, and recovered values over one connection', async () => {
  FakeSocket.ready = { status: 'connected', agent_status: 'connected' }
  FakeSocket.reply = () => ({ status: 'processed', db_status: 'saved', incidents: [] })
  const controller = new AbortController()
  let mode = 'normal'
  const sent = []
  const run = runDashboardSimulation({
    signal: controller.signal,
    getMode: () => mode,
    onConnected() {},
    onFrame: (record) => {
      sent.push(record)
      if (sent.length === 1) mode = 'error'
      if (sent.length === 2) mode = 'normal'
      if (sent.length === 3) controller.abort()
    },
  })
  await assert.rejects(run, { name: 'AbortError' })
  assert.deepEqual(sent.map((record) => record.motor_housing_temp_c), [65, 95, 65])
  assert.equal(new Set(sent.map((record) => record.record_id)).size, 3)
  assert.equal(FakeSocket.instance.closed, true)
})

test('dashboard supports DB-only storage without automatic analysis', async () => {
  FakeSocket.ready = { status: 'connected', agent_status: 'not_connected' }
  FakeSocket.reply = () => ({ status: 'processed', db_status: 'saved', incidents: [] })
  const controller = new AbortController()
  await assert.rejects(runDashboardSimulation({
    signal: controller.signal, getMode: () => 'normal', onConnected() {},
    onFrame: () => controller.abort(),
  }), { name: 'AbortError' })
  assert.equal(FakeSocket.instance.sent.length, 1)
  assert.equal(FakeSocket.instance.closed, true)
})

test('dashboard stops if DB storage is not enabled', async () => {
  FakeSocket.ready = { status: 'connected', agent_status: 'not_connected' }
  FakeSocket.reply = () => ({ status: 'processed', incidents: [] })
  await assert.rejects(runDashboardSimulation({
    signal: new AbortController().signal, getMode: () => 'normal', onConnected() {},
    onFrame: () => assert.fail('unsaved frame must not be displayed'),
  }), /DB 저장에 실패/)
  assert.equal(FakeSocket.instance.sent.length, 1)
  assert.equal(FakeSocket.instance.closed, true)
})

test('both sensor senders support Web Crypto without randomUUID', async (t) => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  const crypto = globalThis.crypto
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true, value: { getRandomValues: (bytes) => crypto.getRandomValues(bytes) },
  })
  t.after(() => Object.defineProperty(globalThis, 'crypto', descriptor))
  FakeSocket.ready = { status: 'connected', agent_status: 'connected' }
  FakeSocket.reply = () => ({ status: 'processed', db_status: 'saved', incidents: [] })
  const controller = new AbortController()
  await assert.rejects(runDashboardSimulation({
    signal: controller.signal, getMode: () => 'normal', onConnected() {},
    onFrame: () => controller.abort(),
  }), { name: 'AbortError' })
  assert.match(FakeSocket.instance.sent[0].record_id, /^DEMO-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}-0$/)
  assert.equal(FakeSocket.instance.closed, true)
  await simulateIncident({ values: {}, duration: 0, signal: new AbortController().signal, onProgress() {}, onEvents() {} })
  assert.match(FakeSocket.instance.sent[0].record_id, /^TEST-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}-0$/)
  assert.equal(FakeSocket.instance.closed, true)
})

test('UUID failure does not open a sensor connection', async (t) => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true, value: { getRandomValues() { throw new Error('random unavailable') } },
  })
  t.after(() => Object.defineProperty(globalThis, 'crypto', descriptor))
  FakeSocket.instance = null
  const options = { signal: new AbortController().signal }
  await assert.rejects(runDashboardSimulation(options), /random unavailable/)
  await assert.rejects(simulateIncident(options), /random unavailable/)
  assert.equal(FakeSocket.instance, null)
})
