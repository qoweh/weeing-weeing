import { useEffect, useState } from 'react'
import ChatWidget from '../chat/ChatWidget.jsx'
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
  onIncidentSelect,
  onSessionExpired,
  children,
}) {
  const [screenZoom, setScreenZoom] = useState(100)

  useEffect(() => {
    document.documentElement.style.zoom = `${screenZoom}%`
    // zoom은 vh까지 같이 배율을 곱하므로, 셸 높이가 화면에 맞도록 배율을 CSS 변수로 넘긴다.
    document.documentElement.style.setProperty(
      '--screen-zoom',
      screenZoom / 100,
    )
    return () => {
      document.documentElement.style.zoom = ''
      document.documentElement.style.removeProperty('--screen-zoom')
    }
  }, [screenZoom])

  useEffect(() => {
    function preventZoomShortcut(event) {
      if (
        (event.ctrlKey || event.metaKey) &&
        (['+', '-', '=', '_'].includes(event.key) ||
          ['NumpadAdd', 'NumpadSubtract'].includes(event.code))
      ) {
        event.preventDefault()
      }
    }
    function preventZoomWheel(event) {
      if (event.ctrlKey || event.metaKey) event.preventDefault()
    }
    window.addEventListener('keydown', preventZoomShortcut, true)
    window.addEventListener('wheel', preventZoomWheel, {
      passive: false,
      capture: true,
    })
    return () => {
      window.removeEventListener('keydown', preventZoomShortcut, true)
      window.removeEventListener('wheel', preventZoomWheel, true)
    }
  }, [])

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
      <ChatWidget
        key={user.employee_no}
        screenZoom={screenZoom}
        onSessionExpired={onSessionExpired}
      />
    </div>
  )
}
