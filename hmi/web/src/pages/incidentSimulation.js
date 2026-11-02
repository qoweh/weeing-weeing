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

export async function simulateIncident({ values, duration, signal, onProgress, onEvents }) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socket = new WebSocket(`${protocol}//${window.location.host}/api/ws/telemetry?context=MINIMAL`)
  const runId = crypto.randomUUID()
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
