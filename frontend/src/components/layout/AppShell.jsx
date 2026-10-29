import { useRef } from 'react'
import Button from '../ui/Button'
import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'
import './layout.scss'
export default function AppShell({
  theme,
  onToggleTheme,
  user,
  onLogout,
  busy,
  page,
  onNavigate,
  children,
}) {
  const chatDialog = useRef(null)
  return (
    <div className="shell">
      <Header
        user={user}
        onLogout={onLogout}
        busy={busy}
        theme={theme}
        onToggleTheme={onToggleTheme}
      />
      <Sidebar page={page} onNavigate={onNavigate} busy={busy} />
      <main className="shell__content" id="main-content">
        {children}
      </main>
      <button
        className="chat-launcher"
        aria-label="챗봇 안내"
        onClick={() => chatDialog.current.showModal()}
      >
        <img src="/assets/ICONS/29bcb.svg" alt="" />
      </button>
      <dialog ref={chatDialog} className="library-dialog">
        <form method="dialog">
          <Button>닫기</Button>
        </form>
        <h2>설비 지원 챗봇</h2>
        <p>챗봇 기능은 준비 중입니다.</p>
      </dialog>
    </div>
  )
}
