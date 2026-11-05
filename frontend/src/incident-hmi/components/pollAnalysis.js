const abortError = () => new DOMException('중단됨', 'AbortError')

function wait(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError())
    const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve() }, ms)
    function cancel() { clearTimeout(timer); reject(abortError()) }
    signal.addEventListener('abort', cancel, { once: true })
  })
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
