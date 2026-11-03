import ChatMarkdown from './ChatMarkdown.js'

import { useEffect, useRef, useState } from 'react'
import useChatSession, { defaultConditions } from './useChatSession.js'
import ChatResponse from './ChatResponse.jsx'
import ChatSourceDialog from './ChatSourceDialog.jsx'
import './chat.scss'

export default function ChatWidget({ screenZoom = 100, onSessionExpired }) {
  const dialog = useRef(null),
    body = useRef(null),
    launcher = useRef(null),
    input = useRef(null)
  const resize = useRef(null),
    drag = useRef(null)
  const [open, setOpen] = useState(false),
    [text, setText] = useState('')
  const [size, setSize] = useState(null),
    [position, setPosition] = useState({ x: 0, y: 0 })
  const [source, setSource] = useState(null)
  const chat = useChatSession(open, onSessionExpired, () => setText(''))
  const conditions = chat.conversation?.conditions || defaultConditions
  const blocked = chat.busy || Boolean(chat.pending)
  const history =
    chat.conversation &&
    !chat.conversations.some(
      (c) => c.conversation_id === chat.conversation.conversation_id,
    )
      ? [chat.conversation, ...chat.conversations]
      : chat.conversations
  useEffect(() => {
    if (body.current) body.current.scrollTop = body.current.scrollHeight
  }, [chat.messages, chat.pending, chat.busy, chat.stream])
  useEffect(() => {
    if (chat.rejectedDraft) setText(chat.rejectedDraft.text)
  }, [chat.rejectedDraft])
  useEffect(() => {
    if (chat.chatMode && !chat.busy) input.current?.focus()
  }, [chat.chatMode, chat.busy])
  useEffect(() => {
    const fit = () => {
      setPosition({ x: 0, y: 0 })
      setSize(null)
    }
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [])
  function startResize(event) {
    if (event.button !== 0) return
    const rect = dialog.current.getBoundingClientRect()
    resize.current = {
      x: event.clientX,
      y: event.clientY,
      width: rect.width / (screenZoom / 100),
      height: rect.height / (screenZoom / 100),
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    event.preventDefault()
  }
  function moveResize(event) {
    if (!resize.current) return
    const start = resize.current
    setSize({
      width: Math.max(
        280,
        start.width + (start.x - event.clientX) / (screenZoom / 100),
      ),
      height: Math.max(
        360,
        start.height + (start.y - event.clientY) / (screenZoom / 100),
      ),
    })
  }
  function keyboardResize(event) {
    const offsets = {
      ArrowLeft: [20, 0],
      ArrowRight: [-20, 0],
      ArrowUp: [0, 20],
      ArrowDown: [0, -20],
    }
    if (!offsets[event.key]) return
    event.preventDefault()
    const rect = dialog.current.getBoundingClientRect(),
      [width, height] = offsets[event.key]
    setSize({
      width: Math.max(280, rect.width / (screenZoom / 100) + width),
      height: Math.max(360, rect.height / (screenZoom / 100) + height),
    })
  }
  function startDrag(event) {
    if (
      event.button !== 0 ||
      event.target.closest('button, input, select, summary')
    )
      return
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      position,
      rect: dialog.current.getBoundingClientRect(),
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    event.preventDefault()
  }
  function moveDrag(event) {
    if (!drag.current) return
    const start = drag.current
    const dx = Math.min(
      window.innerWidth - 8 - start.rect.right,
      Math.max(8 - start.rect.left, event.clientX - start.x),
    )
    const dy = Math.min(
      window.innerHeight - 8 - start.rect.bottom,
      Math.max(8 - start.rect.top, event.clientY - start.y),
    )
    setPosition({
      x: start.position.x + dx / (screenZoom / 100),
      y: start.position.y + dy / (screenZoom / 100),
    })
  }
  function saveConditions(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    chat.saveConditions({
      ...conditions,
      ...Object.fromEntries(
        ['asset_id', 'model', 'date_from', 'date_to'].map((key) => [
          key,
          String(form.get(key) || '').trim() || null,
        ]),
      ),
    })
  }
  function send(event) {
    event.preventDefault()
    if (blocked || !text.trim()) return
    const value = text.trim()
    chat.submit('CHAT', value)
  }
  function close() {
    dialog.current.close()
    setOpen(false)
    launcher.current?.focus()
  }
  const pending = chat.pending
  return (
    <div className="chat-widget">
      <button
        ref={launcher}
        className="chat-launcher"
        aria-label="챗봇 열기"
        aria-expanded={open}
        aria-controls="chat-panel"
        onClick={() => {
          if (!dialog.current.open) dialog.current.show()
          setOpen(true)
        }}
      >
        <img src="/assets/ICONS/29bcb.svg" alt="" />
      </button>
      <dialog
        ref={dialog}
        className="chat-dialog"
        id="chat-panel"
        aria-labelledby="chat-title"
        style={{
          ...(size || {}),
          transform: `translate(${position.x}px, ${position.y}px)`,
        }}
        onClose={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') close()
        }}
      >
        <button
          type="button"
          className="chat-dialog__resize"
          aria-label="챗봇 크기 조절"
          title="드래그하거나 방향키로 크기 조절"
          onPointerDown={startResize}
          onPointerMove={moveResize}
          onLostPointerCapture={() => {
            resize.current = null
          }}
          onPointerUp={() => {
            resize.current = null
          }}
          onPointerCancel={() => {
            resize.current = null
          }}
          onKeyDown={keyboardResize}
        >
          <span aria-hidden="true" />
        </button>
        <header
          className="chat-dialog__header"
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onLostPointerCapture={() => {
            drag.current = null
          }}
          onPointerUp={() => {
            drag.current = null
          }}
          onPointerCancel={() => {
            drag.current = null
          }}
        >
          <div className="chat-dialog__identity">
            <span className="chat-dialog__mark" aria-hidden="true">
              ✦
            </span>
            <div>
              <h2 id="chat-title">설비 지원 챗봇</h2>
              <p>{chat.chatMode ? '자유 대화' : 'FAQ 안내'}</p>
            </div>
          </div>
          <button
            className="chat-dialog__close"
            aria-label="챗봇 닫기"
            onClick={close}
          >
            ✕
          </button>
        </header>
        <div className="chat-controls">
          <label>
            내 대화
            <select
              value={chat.conversation?.conversation_id || ''}
              onChange={(event) => chat.selectConversation(event.target.value)}
              disabled={chat.busy}
            >
              <option value="">대화를 선택하세요</option>
              {history.map((c) => (
                <option key={c.conversation_id} value={c.conversation_id}>
                  {c.title} ·{' '}
                  {new Date(c.updated_at).toLocaleDateString('ko-KR')}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => {
              setText('')
              chat.newConversation()
            }}
            disabled={chat.busy}
          >
            새 대화
          </button>
          {chat.moreConversations && (
            <button
              type="button"
              onClick={chat.moreHistory}
              disabled={chat.busy}
            >
              목록 더 보기
            </button>
          )}
        </div>
        <details className="chat-conditions">
          <summary>
            검색 조건 ·{' '}
            {['asset_id', 'model', 'date_from', 'date_to']
              .map((key) => conditions[key])
              .filter(Boolean)
              .join(' / ') || '전체 자료'}
          </summary>
          <form
            key={`${chat.conversation?.conversation_id}:${JSON.stringify(conditions)}`}
            onSubmit={saveConditions}
          >
            <label>
              설비 ID
              <input
                name="asset_id"
                maxLength={100}
                defaultValue={conditions.asset_id || ''}
                placeholder="전체 설비"
                disabled={blocked}
              />
            </label>
            <label>
              설비 모델
              <input
                name="model"
                maxLength={100}
                defaultValue={conditions.model || ''}
                placeholder="지정 안 함"
                disabled={blocked}
              />
            </label>
            <label>
              조치 시작일
              <input
                name="date_from"
                type="date"
                defaultValue={conditions.date_from || ''}
                disabled={blocked}
              />
            </label>
            <label>
              조치 종료일
              <input
                name="date_to"
                type="date"
                defaultValue={conditions.date_to || ''}
                disabled={blocked}
              />
            </label>
            <p>
              기간은 정비 조치일 기준입니다. 모델 조건은 매뉴얼 검색에
              사용합니다.
            </p>
            <button disabled={blocked}>조건 적용</button>
          </form>
        </details>
        <div ref={body} className="chat-dialog__body">
          {!chat.messages.length && (
            <div className="chat-dialog__message">
              <strong>무엇을 도와드릴까요?</strong>
              <p>
                FAQ 주제와 질문을 선택하거나, 채팅 시작을 눌러 매뉴얼·정비이력을
                물어보세요.
              </p>
            </div>
          )}
          <div
            className="chat-dialog__conversation"
            role="log"
            aria-label="대화 내용"
            aria-live="polite"
            aria-relevant="additions"
          >
            {chat.messages.map((message) => (
              <div
                key={message.sequence}
                className={`chat-dialog__message-row chat-dialog__message-row--${message.role}`}
              >
                {message.role === 'assistant' && (
                  <span
                    className="chat-dialog__message-icon"
                    aria-hidden="true"
                  >
                    ✦
                  </span>
                )}
                <div className="chat-dialog__message">
                  {message.response ? (
                    <ChatResponse
                      response={message.response}
                      onSource={setSource}
                    />
                  ) : (
                    message.content
                  )}
                </div>
              </div>
            ))}
            {pending &&
              !chat.messages.some(
                (message) =>
                  message.request_id === pending.submission.request_id,
              ) && (
                <div className="chat-dialog__message-row chat-dialog__message-row--user">
                  <div className="chat-dialog__message">
                    {pending.displayQuestion ||
                      pending.submission.question ||
                      chat.questions.find(
                        (q) => q.faq_id === pending.submission.faq_id,
                      )?.question ||
                      'FAQ 질문 선택'}
                  </div>
                </div>
              )}
            {chat.busy && (
              <p role="status">
                {{
                  accepted: '요청을 확인하고 있습니다…',
                  searching: '자료 검색 중…',
                  generating: '답변 작성 중…',
                  verifying: '근거 검토 중…',
                  saving: '답변을 저장하고 있습니다…',
                  delivering: '검증된 답변을 표시하고 있습니다…',
                }[chat.stream?.phase] ||
                  '답변과 대화 상태를 확인하고 있습니다…'}
              </p>
            )}
            {chat.busy &&
              chat.stream?.text &&
              !chat.messages.some(
                (message) =>
                  message.role === 'assistant' &&
                  message.request_id === chat.stream.requestId,
              ) && (
                <div
                  className="chat-dialog__message-row chat-dialog__message-row--assistant"
                  aria-live="off"
                >
                  <span
                    className="chat-dialog__message-icon"
                    aria-hidden="true"
                  >
                    ✦
                  </span>
                  <div className="chat-dialog__message">
                    <ChatMarkdown>{chat.stream.text}</ChatMarkdown>
                  </div>
                </div>
              )}
            {pending && !chat.busy && (
              <div className="chat-pending" role="status">
                {pending.response ? (
                  <ChatResponse
                    response={pending.response}
                    onSource={setSource}
                  />
                ) : (
                  <p>
                    {pending.state === 'UNKNOWN'
                      ? '처리 결과와 과금 여부를 확인할 수 없어 자동 재전송하지 않습니다.'
                      : pending.state === 'FAILED'
                        ? pending.error_code === 'FAQ_NOT_FOUND'
                          ? '선택한 FAQ를 더 이상 조회할 수 없습니다. 목록을 새로 받아 주세요.'
                          : '요청 실행을 준비하지 못했습니다.'
                        : '요청이 서버에서 계속 처리 중일 수 있습니다. 상태를 확인해 주세요.'}
                  </p>
                )}
                <button type="button" onClick={chat.checkPending}>
                  상태 확인
                </button>
                {pending.retry_allowed && (
                  <button type="button" onClick={chat.retryPending}>
                    같은 요청 다시 시도
                  </button>
                )}
                {pending.error_code === 'FAQ_NOT_FOUND' && (
                  <button type="button" onClick={chat.reloadMissingFaq}>
                    FAQ 목록 새로고침
                  </button>
                )}
              </div>
            )}
          </div>
          {chat.error && (
            <p role="alert" className="chat-error">
              {chat.error}
            </p>
          )}
          {!chat.chatMode && (
            <section className="chat-dialog__examples" aria-label="FAQ 목록">
              <h3>{chat.topic?.title || 'FAQ 주제'}</h3>
              {chat.topic && (
                <button type="button" onClick={() => chat.loadFaq()}>
                  주제 목록으로
                </button>
              )}
              {chat.faqLoading ? (
                <p role="status">FAQ를 불러오는 중입니다.</p>
              ) : chat.faqError ? (
                <p role="alert">
                  {chat.faqError}{' '}
                  <button onClick={() => chat.loadFaq(chat.topic)}>
                    다시 불러오기
                  </button>
                </p>
              ) : chat.topic ? (
                chat.questions.length ? (
                  chat.questions.map((q) => (
                    <button
                      key={q.faq_id}
                      type="button"
                      disabled={blocked}
                      onClick={() => chat.submit('FAQ', q)}
                    >
                      {q.question}
                    </button>
                  ))
                ) : (
                  <p>등록된 질문이 없습니다. 채팅 시작을 이용해 주세요.</p>
                )
              ) : chat.topics.length ? (
                chat.topics.map((t) => (
                  <button
                    key={t.topic_id}
                    type="button"
                    onClick={() => chat.loadFaq(t)}
                  >
                    {t.title} <span aria-hidden="true">›</span>
                  </button>
                ))
              ) : (
                <p>등록된 FAQ 주제가 없습니다. 채팅 시작을 이용해 주세요.</p>
              )}
            </section>
          )}
        </div>
        <footer className="chat-dialog__footer">
          <div className="chat-mode-buttons">
            <button type="button" onClick={chat.showFaq}>
              FAQ 목록
            </button>
            <button
              type="button"
              disabled={blocked}
              aria-pressed={chat.chatMode}
              onClick={chat.startChat}
            >
              채팅 시작
            </button>
          </div>
          {chat.chatMode && (
            <form className="chat-dialog__composer" onSubmit={send}>
              <textarea
                ref={input}
                aria-label="챗봇 질문"
                value={text}
                onChange={(event) => setText(event.target.value)}
                maxLength={2000}
                rows={2}
                placeholder="매뉴얼이나 정비이력을 물어보세요"
                disabled={blocked}
                onKeyDown={(event) => {
                  if (
                    event.key === 'Enter' &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault()
                    event.currentTarget.form.requestSubmit()
                  }
                }}
              />
              <button disabled={blocked || !text.trim()} aria-label="질문 전송">
                ↑
              </button>
            </form>
          )}
          <p>대화 기록은 본인만 조회할 수 있습니다.</p>
        </footer>
      </dialog>
      {source && (
        <ChatSourceDialog
          source={source}
          onClose={() => setSource(null)}
          onSessionExpired={onSessionExpired}
        />
      )}
    </div>
  )
}
