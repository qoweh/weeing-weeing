import { useEffect, useRef, useState } from 'react'
import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'
import './layout.scss'

const chatSuggestions = {
  start: [
    { label: '설비 매뉴얼 찾기', next: 'manual' },
    { label: '정비 이력 확인하기', next: 'maintenance' },
    { label: '이상 상황 살펴보기', next: 'incident' },
  ],
  manual: [
    { label: '설비 모델로 매뉴얼 찾기', next: 'start' },
    { label: '매뉴얼 업로드 방법 알아보기', next: 'start' },
    { label: '다른 주제 살펴보기', next: 'start' },
  ],
  maintenance: [
    { label: '설비별 정비 이력 찾기', next: 'start' },
    { label: '정비 보고서 확인하기', next: 'start' },
    { label: '다른 주제 살펴보기', next: 'start' },
  ],
  incident: [
    { label: '최근 이상 이력 확인하기', next: 'start' },
    { label: '이상 보고서 살펴보기', next: 'start' },
    { label: '다른 주제 살펴보기', next: 'start' },
  ],
}

export default function AppShell({
  theme,
  onToggleTheme,
  user,
  onLogout,
  busy,
  page,
  onNavigate,
  onIncidentSelect,
  children,
}) {
  const chatDialog = useRef(null)
  const chatBody = useRef(null)
  const chatResize = useRef(null)
  const chatDrag = useRef(null)
  const [chatInput, setChatInput] = useState('')
  const [chatMessages, setChatMessages] = useState([])
  const [chatSize, setChatSize] = useState(null)
  const [chatPosition, setChatPosition] = useState({ x: 0, y: 0 })
  const [suggestionGroup, setSuggestionGroup] = useState('start')
  const [screenZoom, setScreenZoom] = useState(100)

  useEffect(() => {
    document.documentElement.style.zoom = `${screenZoom}%`
    // zoom은 vh까지 같이 배율을 곱하므로, 셸 높이가 화면에 맞도록 배율을 CSS 변수로 넘긴다.
    document.documentElement.style.setProperty('--screen-zoom', screenZoom / 100)
    return () => {
      document.documentElement.style.zoom = ''
      document.documentElement.style.removeProperty('--screen-zoom')
    }
  }, [screenZoom])

  useEffect(() => {
    function preventZoomShortcut(event) {
      if ((event.ctrlKey || event.metaKey) &&
        (['+', '-', '=', '_'].includes(event.key) || ['NumpadAdd', 'NumpadSubtract'].includes(event.code))) {
        event.preventDefault()
      }
    }
    function preventZoomWheel(event) {
      if (event.ctrlKey || event.metaKey) event.preventDefault()
    }
    window.addEventListener('keydown', preventZoomShortcut, true)
    window.addEventListener('wheel', preventZoomWheel, { passive: false, capture: true })
    return () => {
      window.removeEventListener('keydown', preventZoomShortcut, true)
      window.removeEventListener('wheel', preventZoomWheel, true)
    }
  }, [])

  useEffect(() => {
    if (chatBody.current) chatBody.current.scrollTop = chatBody.current.scrollHeight
  }, [chatMessages])

  function sendChatMessage(event) {
    event.preventDefault()
    const message = chatInput.trim()
    if (!message) return
    setChatMessages((messages) => [
      ...messages,
      { role: 'user', text: message },
      { role: 'assistant', text: '메시지를 확인했습니다. 현재는 테스트용 응답이며, 실제 설비 정보 조회와 답변 기능은 준비 중입니다.' },
    ])
    setChatInput('')
  }

  function selectChatSuggestion(suggestion) {
    setChatMessages((messages) => [
      ...messages,
      { role: 'user', text: suggestion.label },
      { role: 'assistant', text: suggestion.next === 'start'
        ? '테스트용 대화입니다. 실제 정보 조회 기능은 준비 중입니다. 다른 주제도 선택해 보세요.'
        : '테스트용 대화입니다. 이어서 궁금한 내용을 선택해 보세요.' },
    ])
    setSuggestionGroup(suggestion.next)
  }

  function startChatResize(event) {
    if (event.button !== 0) return
    const rect = chatDialog.current.getBoundingClientRect()
    chatResize.current = { x: event.clientX, y: event.clientY, width: rect.width / (screenZoom / 100), height: rect.height / (screenZoom / 100) }
    event.currentTarget.setPointerCapture(event.pointerId)
    event.preventDefault()
  }

  function moveChatResize(event) {
    if (!chatResize.current) return
    const start = chatResize.current
    setChatSize({ width: Math.max(0, start.width + (start.x - event.clientX) / (screenZoom / 100)), height: Math.max(0, start.height + (start.y - event.clientY) / (screenZoom / 100)) })
  }

  function resizeChatWithKeyboard(event) {
    const offsets = { ArrowLeft: [20, 0], ArrowRight: [-20, 0], ArrowUp: [0, 20], ArrowDown: [0, -20] }
    if (!offsets[event.key]) return
    event.preventDefault()
    const rect = chatDialog.current.getBoundingClientRect()
    const [width, height] = offsets[event.key]
    setChatSize({ width: Math.max(0, rect.width / (screenZoom / 100) + width), height: Math.max(0, rect.height / (screenZoom / 100) + height) })
  }

  function startChatDrag(event) {
    if (event.button !== 0 || event.target.closest('button')) return
    const rect = chatDialog.current.getBoundingClientRect()
    chatDrag.current = { x: event.clientX, y: event.clientY, position: chatPosition, rect }
    event.currentTarget.setPointerCapture(event.pointerId)
    event.preventDefault()
  }

  function moveChatDrag(event) {
    if (!chatDrag.current) return
    const start = chatDrag.current
    const dx = Math.min(window.innerWidth - 8 - start.rect.right, Math.max(8 - start.rect.left, event.clientX - start.x))
    const dy = Math.min(window.innerHeight - 8 - start.rect.bottom, Math.max(8 - start.rect.top, event.clientY - start.y))
    setChatPosition({ x: start.position.x + dx / (screenZoom / 100), y: start.position.y + dy / (screenZoom / 100) })
  }
  return (
    <div className="shell">
      <Header
        user={user}
        onLogout={onLogout}
        busy={busy}
        theme={theme}
        onToggleTheme={onToggleTheme}
        screenZoom={screenZoom}
        onChangeScreenZoom={setScreenZoom}
        onIncidentSelect={onIncidentSelect}
      />
      <Sidebar page={page} onNavigate={onNavigate} busy={busy} />
      <main className="shell__content" id="main-content">
        {children}
      </main>
      <div className="chat-widget">
        <button
          className="chat-launcher"
          aria-label="챗봇 안내"
          onClick={() => {
            if (!chatDialog.current.open) chatDialog.current.show()
          }}
        >
          <img src="/assets/ICONS/29bcb.svg" alt="" />
        </button>
        <dialog
          ref={chatDialog}
          className="chat-dialog"
          aria-labelledby="chat-title"
          style={{ ...(chatSize && { width: chatSize.width, height: chatSize.height }), transform: `translate(${chatPosition.x}px, ${chatPosition.y}px)` }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') chatDialog.current.close()
          }}
        >
          <button
            type="button"
            className="chat-dialog__resize"
            aria-label="챗봇 크기 조절"
            title="드래그하거나 방향키로 크기 조절"
            onPointerDown={startChatResize}
            onPointerMove={moveChatResize}
            onPointerUp={() => { chatResize.current = null }}
            onPointerCancel={() => { chatResize.current = null }}
            onLostPointerCapture={() => { chatResize.current = null }}
            onKeyDown={resizeChatWithKeyboard}
          ><span aria-hidden="true" /></button>
          <header
            className="chat-dialog__header"
            onPointerDown={startChatDrag}
            onPointerMove={moveChatDrag}
            onPointerUp={() => { chatDrag.current = null }}
            onPointerCancel={() => { chatDrag.current = null }}
            onLostPointerCapture={() => { chatDrag.current = null }}
          >
            <div className="chat-dialog__identity">
              <span className="chat-dialog__mark" aria-hidden="true">✦</span>
              <div>
                <h2 id="chat-title">설비 지원 챗봇</h2>
                <p><span className="chat-dialog__status-dot" /> 테스트 모드</p>
              </div>
            </div>
            <form method="dialog">
              <button className="chat-dialog__close" aria-label="챗봇 닫기" autoFocus>
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
              </button>
            </form>
          </header>
          <div className="chat-dialog__body" ref={chatBody}>
            <p className="chat-dialog__date">설비 지원 안내</p>
            <div className="chat-dialog__message-row">
              <span className="chat-dialog__message-icon" aria-hidden="true">✦</span>
              <div className="chat-dialog__message">
                <strong>안녕하세요!</strong>
                <p>메시지를 보내면 테스트용 응답을 확인할 수 있습니다.</p>
              </div>
            </div>
            <div className="chat-dialog__conversation" aria-live="polite" aria-relevant="additions">
              {chatMessages.map((message, index) => (
                <div key={index} className={`chat-dialog__message-row chat-dialog__message-row--${message.role}`}>
                  {message.role === 'assistant' && <span className="chat-dialog__message-icon" aria-hidden="true">✦</span>}
                  <div className="chat-dialog__message">{message.text}</div>
                </div>
              ))}
            </div>
            <div className="chat-dialog__examples">
              <p>{suggestionGroup === 'start' ? '이런 내용을 물어볼 수 있어요' : '이어서 물어볼 수 있어요'}</p>
              {chatSuggestions[suggestionGroup].map((suggestion) => (
                <button key={suggestion.label} type="button" onClick={() => selectChatSuggestion(suggestion)}>
                  {suggestion.label}
                </button>
              ))}
            </div>
          </div>
          <div className="chat-dialog__footer">
            <form className="chat-dialog__composer" onSubmit={sendChatMessage}>
              <input type="text" aria-label="메시지 입력" placeholder="메시지를 입력하세요" value={chatInput} onChange={(event) => setChatInput(event.target.value)} />
              <button type="submit" aria-label="메시지 보내기" disabled={!chatInput.trim()}>
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 19V5m0 0L6.5 10.5M12 5l5.5 5.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
            </form>
            <p>테스트용 응답입니다 · 실제 설비 정보와 연결되지 않았습니다</p>
          </div>
        </dialog>
      </div>
    </div>
  )
}
