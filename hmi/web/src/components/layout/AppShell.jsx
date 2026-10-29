import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'
import './layout.scss'
export default function AppShell({ theme, onToggleTheme, user, onLogout, busy, page, onNavigate, children }) {
  return <div className="shell"><Header user={user} onLogout={onLogout} busy={busy} theme={theme} onToggleTheme={onToggleTheme} /><Sidebar page={page} onNavigate={onNavigate} busy={busy} /><main className="shell__content" id="main-content">{children}</main></div>
}
