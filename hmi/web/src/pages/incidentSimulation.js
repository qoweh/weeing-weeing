import { newRequestId } from '../api/requestId.js'

const abortError = () => new DOMException('중단됨', 'AbortError')

function wait(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError())
    const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve() }, ms)
    function cancel() { clearTimeout(timer); reject(abortError()) }
    signal.addEventListener('abort', cancel, { once: true })
  })
}

function nextMessage(socket, signal, timeout = 15000) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError())
    const timer = setTimeout(() => finish(new Error('서버 응답 시간이 초과됐습니다. 서버에서 처리가 계속될 수 있습니다.')), timeout)
    function finish(error, data) {
      clearTimeout(timer)
      socket.removeEventListener('message', message)
      socket.removeEventListener('close', closed)
      socket.removeEventListener('error', failed)
      signal.removeEventListener('abort', cancel)
      if (error) reject(error); else resolve(data)
    }
    function message(event) {
      try { finish(null, JSON.parse(event.data)) } catch { finish(new Error('서버 응답을 읽을 수 없습니다.')) }
    }
    function closed() { finish(new Error('센서 연결이 종료됐습니다. 서버 상태를 확인해 주세요.')) }
    function failed() { finish(new Error('센서 서버에 연결하지 못했습니다.')) }
    function cancel() { finish(abortError()) }
    socket.addEventListener('message', message)
    socket.addEventListener('close', closed)
    socket.addEventListener('error', failed)
    signal.addEventListener('abort', cancel, { once: true })
  })
}

export const demoNormalValues = Object.freeze({
  infeed_present: false, outfeed_present: false, rpm: 1015,
  dc_input_current_a: 0.0918, dc_bus_voltage_v: 24, motor_housing_temp_c: 65,
  de_vibration_rms_g: 0.06, de_kurtosis: 5, nde_vibration_rms_g: 0.055,
  nde_kurtosis: 4.5,
})

// 한 연결의 탐지 상태를 유지해야 같은 사건의 발생과 회복을 관찰할 수 있다.
export async function runDashboardSimulation({ signal, getMode, onFrame, onConnected }) {
  const runId = newRequestId()
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socket = new WebSocket(`${protocol}//${window.location.host}/api/ws/telemetry?context=MINIMAL&origin=SIMULATION&interval_s=1`)
  try {
    const ready = await nextMessage(socket, signal)
    if (ready.status !== 'connected') throw new Error(ready.code === 'producer_busy' ? '다른 센서 전송이 진행 중입니다. 먼저 해당 전송을 중단해 주세요.' : `연결이 거부됐습니다: ${ready.code || ready.status}`)
    onConnected()
    for (let count = 0; !signal.aborted; count += 1) {
      const startedAt = performance.now()
      const mode = getMode()
      const record = {
        record_id: `DEMO-${runId}-${count}`, timestamp: new Date().toISOString(),
        process_id: 'BAT-TRANSFER-01', asset_id: 'BLDC-001', schema_version: '3.0.0',
        ...demoNormalValues, motor_housing_temp_c: mode === 'error' ? 95 : 65,
      }
      const pending = nextMessage(socket, signal)
      socket.send(JSON.stringify(record))
      const response = await pending
      if (response.status !== 'processed' || response.record_id !== record.record_id || response.db_status !== 'saved') throw new Error('센서값 처리 또는 DB 저장에 실패했습니다. 연결을 확인해 주세요.')
      onFrame(record, response)
      await wait(Math.max(0, 1000 - (performance.now() - startedAt)), signal)
    }
  } finally {
    socket.close()
  }
}

export async function simulateIncident({ values, duration, signal, onProgress, onEvents }) {
  const runId = newRequestId()
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socket = new WebSocket(`${protocol}//${window.location.host}/api/ws/telemetry?context=MINIMAL&origin=SIMULATION&interval_s=1`)
  try {
    const ready = await nextMessage(socket, signal)
    if (ready.status !== 'connected') {
      throw new Error(ready.code === 'producer_busy' ? '다른 센서 송신이 진행 중입니다. 종료한 뒤 다시 시도해 주세요.' : `센서 연결이 거부됐습니다: ${ready.code || ready.status}`)
    }
    if (ready.agent_status !== 'connected') throw new Error('자동 분석이 꺼져 있습니다. 서버의 ANALYSIS_AUTO_ENABLED 설정을 켜고 재시작해 주세요.')
    for (let count = 0; count <= duration; count += 1) {
      if (signal.aborted) throw abortError()
      const record = {
        record_id: `TEST-${runId}-${count}`,
        timestamp: new Date().toISOString(),
        process_id: 'BAT-TRANSFER-01', asset_id: 'BLDC-001', schema_version: '3.0.0',
        ...values,
      }
      const responsePromise = nextMessage(socket, signal)
      socket.send(JSON.stringify(record))
      const response = await responsePromise
      if (response.status !== 'processed' || response.record_id !== record.record_id) throw new Error(`센서 처리 실패: ${response.code || response.status || '응답 불일치'}`)
      if (response.db_status === 'failed') throw new Error('센서 탐지 결과를 DB에 저장하지 못했습니다. 자동 재전송하지 않습니다.')
      onEvents(response.incidents || [], response.analysis_jobs || [])
      onProgress(count, duration)
      if (response.error_entries?.length) return response.error_entries
      if (count < duration) await wait(1000, signal)
    }
    return []
  } finally {
    socket.close()
  }
}

export async function pollAnalysis(id, getAnalysis, signal, onUpdate) {
  const deadline = Date.now() + 10 * 60 * 1000
  while (!signal.aborted && Date.now() < deadline) {
    const result = await getAnalysis(id)
    if (signal.aborted) throw abortError()
    onUpdate(result)
    if (['COMPLETED', 'FAILED'].includes(result.job?.status)) return
    await wait(2000, signal)
  }
  if (signal.aborted) throw abortError()
  throw new Error('결과 확인 시간이 초과됐습니다. 서버에서 분석이 계속될 수 있습니다.')
}
