// fetch로 SSE를 읽어 Bearer 인증·POST·취소 신호를 기존 요청과 동일하게 유지한다.
export async function readChatStream(
  response,
  { onEvent = () => {}, signal } = {},
) {
  if (
    !response.headers.get('content-type')?.includes('text/event-stream') ||
    !response.body
  )
    throw new Error('서버가 채팅 스트림을 반환하지 않았습니다.')
  const reader = response.body.getReader()
  const abort = () => {
    reader.cancel().catch(() => {})
  }
  signal?.addEventListener('abort', abort, { once: true })
  const decoder = new TextDecoder('utf-8', { fatal: true })
  let buffer = '',
    final = null
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      const { value, done } = await reader.read()
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      buffer += done
        ? decoder.decode()
        : decoder.decode(value, { stream: true })
      if (buffer.length > 1_000_000)
        throw new Error('채팅 이벤트 크기가 너무 큽니다.')
      let boundary
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index).replace(/\r\n/g, '\n')
        buffer = buffer.slice(boundary.index + boundary[0].length)
        const lines = frame.split('\n')
        const data = lines
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n')
        if (!data) continue // keep-alive 주석
        const event = JSON.parse(data)
        const named = lines
          .find((line) => line.startsWith('event:'))
          ?.slice(6)
          .trim()
        if (named && named !== event.event)
          throw new Error('채팅 이벤트 형식이 올바르지 않습니다.')
        if (event.event === 'error') {
          const error = new Error(event.message || '채팅 전송이 중단됐습니다.')
          error.status = event.status_code
          // 이미 시작된 스트림 오류를 미접수 거절로 오인해 새 ID로 재전송하지 않는다.
          error.data =
            event.request_reserved === false
              ? { stream_started: true }
              : { state: 'UNKNOWN', stream_started: true }
          throw error
        }
        if (event.event === 'done') {
          if (!event.request?.submission?.request_id || !event.request?.state)
            throw new Error('채팅 완료 상태가 올바르지 않습니다.')
          final = event.request
          await onEvent(event)
          return final
        }
        if (!['progress', 'delta'].includes(event.event))
          throw new Error('알 수 없는 채팅 이벤트입니다.')
        if (event.event === 'delta' && typeof event.text !== 'string')
          throw new Error('채팅 본문 형식이 올바르지 않습니다.')
        await onEvent(event)
      }
      if (done) break
    }
    throw new Error(
      '채팅 전송이 끊겼습니다. 상태 확인 버튼으로 결과를 확인하세요.',
    )
  } finally {
    signal?.removeEventListener('abort', abort)
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
