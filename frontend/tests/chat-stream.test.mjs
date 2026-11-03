import { afterEach, test } from 'node:test'
import assert from 'node:assert/strict'
import { setAccessToken } from '../src/api/client.js'
import { submitChatRequest, isChatRequestRejected } from '../src/api/chat.js'
import { readChatStream } from '../src/api/sse.js'

const originalFetch = globalThis.fetch
const submission = {
  kind: 'CHAT',
  request_id: 'stream-1',
  question: '현재 경고',
}
const view = {
  conversation_id: 'c1',
  submission,
  state: 'COMPLETED',
  retry_allowed: false,
}
const frame = (event) =>
  `event: ${event.event}\r\ndata: ${JSON.stringify(event)}\r\n\r\n`
function stream(events, fragment = 7) {
  const bytes = new TextEncoder().encode(
    ': heartbeat\r\n\r\n' + events.map(frame).join(''),
  )
  return new Response(
    new ReadableStream({
      start(controller) {
        for (let i = 0; i < bytes.length; i += fragment)
          controller.enqueue(bytes.slice(i, i + fragment))
        controller.close()
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )
}
afterEach(() => {
  globalThis.fetch = originalFetch
  setAccessToken('')
})

test('인증된 POST 스트림과 UTF-8 분할·공백·완료 상태를 읽는다', async () => {
  const events = [],
    calls = []
  setAccessToken('fake-session')
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return stream(
      [
        {
          event: 'progress',
          request_id: submission.request_id,
          phase: 'verifying',
        },
        {
          event: 'delta',
          request_id: submission.request_id,
          text: '## 온도\n\n',
        },
        {
          event: 'delta',
          request_id: submission.request_id,
          text: '**86℃** 입니다.',
        },
        { event: 'done', request: view },
      ],
      1,
    )
  }
  const result = await submitChatRequest('c1', submission, {
    onEvent: (e) => events.push(e),
  })
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], '/api/chat/conversations/c1/messages/stream')
  assert.equal(calls[0][1].headers.Authorization, 'Bearer fake-session')
  assert.equal(result.state, 'COMPLETED')
  assert.equal(
    events
      .filter((e) => e.event === 'delta')
      .map((e) => e.text)
      .join(''),
    '## 온도\n\n**86℃** 입니다.',
  )
})

test('완료 이벤트 없는 연결 중단은 실패이며 POST를 재전송하지 않는다', async () => {
  let calls = 0
  globalThis.fetch = async () => {
    calls++
    return stream([{ event: 'progress', phase: 'generating' }])
  }
  await assert.rejects(
    submitChatRequest('c1', submission, { onEvent() {} }),
    /상태 확인/,
  )
  assert.equal(calls, 1)
})

test('스트림 시작 뒤 오류는 접수되지 않은 거절로 분류하지 않는다', async () => {
  globalThis.fetch = async () =>
    stream([
      { event: 'error', status_code: 409, message: '상태를 확인해 주세요' },
    ])
  await assert.rejects(
    submitChatRequest('c1', submission, { onEvent() {} }),
    (error) => !isChatRequestRejected(error) && error.data.state === 'UNKNOWN',
  )
})

test('이미 취소된 신호로 스트림 본문을 계속 읽지 않는다', async () => {
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(
    readChatStream(stream([{ event: 'done', request: view }]), {
      signal: controller.signal,
    }),
    { name: 'AbortError' },
  )
})

test('FAQ 선택은 스트림 콜백을 넘겨도 기존 JSON 경로만 사용한다', async () => {
  const urls = []
  globalThis.fetch = async (url) => {
    urls.push(url)
    return new Response(JSON.stringify(view), {
      headers: { 'Content-Type': 'application/json' },
    })
  }
  await submitChatRequest(
    'c1',
    { kind: 'FAQ', request_id: 'faq1', faq_id: 'FAQ-1' },
    {
      onEvent() {
        throw new Error('must not stream')
      },
    },
  )
  assert.equal(urls[0], '/api/chat/conversations/c1/faq-selections')
})

test('서버가 예약 전 거절을 확인한 충돌은 기존 입력 복구 정책으로 처리한다', async () => {
  globalThis.fetch = async () =>
    stream([
      {
        event: 'error',
        status_code: 409,
        request_reserved: false,
        message: '채팅 시작으로 전환해 주세요',
      },
    ])
  await assert.rejects(
    submitChatRequest('c1', submission, { onEvent() {} }),
    isChatRequestRejected,
  )
})

test('다음 조각을 기다리는 중 취소해도 reader를 종료한다', async () => {
  const abort = new AbortController()
  let cancelled = false
  const response = new Response(
    new ReadableStream({
      cancel() {
        cancelled = true
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )
  const pending = readChatStream(response, { signal: abort.signal })
  abort.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  assert.equal(cancelled, true)
})
