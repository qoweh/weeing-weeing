import { request } from './client.js'

const root = '/chat/conversations'
const path = (id) => `${root}/${encodeURIComponent(id)}`

// 실패 HTTP에도 저장된 요청 상태가 있으므로 일반 네트워크 장애와 구분한다.
async function chatRequest(url, options) {
  try {
    return await request(url, options)
  } catch (error) {
    if (
      [404, 409, 503].includes(error.status) &&
      error.data?.state &&
      error.data?.submission &&
      error.data?.conversation_id
    )
      return error.data
    throw error
  }
}
export const listFaqTopics = (signal) => request('/chat/faq/topics', { signal })
export const listFaqQuestions = (id, signal) =>
  request(`/chat/faq/topics/${encodeURIComponent(id)}/questions`, { signal })
export const listChatConversations = (offset = 0, signal) =>
  request(`${root}?limit=50&offset=${offset}`, { signal })
export const createChatConversation = (body = {}, signal) =>
  request(root, { method: 'POST', body, signal })
export const updateChatConversation = (id, body, signal) =>
  request(path(id), { method: 'PATCH', body, signal })
export const getChatMessages = (id, after = 0, signal) =>
  request(`${path(id)}?limit=200&after_sequence=${after}`, { signal })
export const getChatRequest = (id, requestId, signal) =>
  chatRequest(`${path(id)}/requests/${encodeURIComponent(requestId)}`, {
    signal,
  })
export function submitChatRequest(
  id,
  submission,
  { retry = false, signal } = {},
) {
  const faq = submission.kind === 'FAQ'
  const body = faq
    ? { request_id: submission.request_id, faq_id: submission.faq_id }
    : {
        request_id: submission.request_id,
        question: submission.question,
        ...(submission.conditions != null
          ? { conditions: submission.conditions }
          : {}),
      }
  return chatRequest(
    `${path(id)}/${faq ? 'faq-selections' : 'messages'}${retry ? '?retry=true' : ''}`,
    { method: 'POST', body, signal },
  )
}
export const processing = (view) =>
  ['RESERVED', 'RUNNING'].includes(view?.state)

// 상태 확인은 GET만 사용한다. 같은 질문을 새 ID로 자동 전송하지 않는다.
export async function waitForChatRequest(
  id,
  initial,
  { signal, onUpdate = () => {}, timeoutMs = 180_000, intervalMs = 1000 } = {},
) {
  let view = initial
  const end = Date.now() + timeoutMs
  onUpdate(view)
  while (processing(view)) {
    if (Date.now() >= end)
      throw new Error(
        '아직 처리가 끝나지 않았습니다. 상태 확인 버튼으로 결과를 확인하세요.',
      )
    await new Promise((resolve, reject) => {
      if (signal?.aborted)
        return reject(new DOMException('Aborted', 'AbortError'))
      const abort = () => {
        clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      }
      const timer = setTimeout(() => {
        signal?.removeEventListener('abort', abort)
        resolve()
      }, intervalMs)
      signal?.addEventListener('abort', abort, { once: true })
    })
    view = await getChatRequest(id, initial.submission.request_id, signal)
    onUpdate(view)
  }
  return view
}

export const getChatDocumentFile = (source, signal) => {
  const params = new URLSearchParams({
    doc_id: source.doc_id,
    doc_version: source.doc_version,
  })
  return request(`/documents/original?${params}`, {
    signal,
    responseType: 'blob',
  })
}

// IP의 HTTP 시연 환경에서도 UUID를 만들 수 있게 Web Crypto로 대체한다.
export function newChatRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = [...bytes]
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

// 요청 상태가 없는 입력·인증·모드 거절은 접수 실패다. 유실·5xx·UNKNOWN과 구분한다.
export const isChatRequestRejected = (error) =>
  [400, 401, 403, 404, 409, 422].includes(error?.status) && !error.data?.state
