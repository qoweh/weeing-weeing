import ChatWidget from '../chat/ChatWidget.jsx'
import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'
import './layout.scss'
export default function AppShell({ theme, onToggleTheme, user, onLogout, busy, page, onNavigate, onIncidentSelect, onSessionExpired, children }) {
  return <div className="shell"><Header user={user} onLogout={onLogout} busy={busy} theme={theme} onToggleTheme={onToggleTheme} onIncidentSelect={onIncidentSelect} onSessionExpired={onSessionExpired} /><Sidebar user={user} page={page} onNavigate={onNavigate} busy={busy} /><main className="shell__content" id="main-content">{children}</main><ChatWidget key={user.employee_no} onSessionExpired={onSessionExpired} /></div>
}
