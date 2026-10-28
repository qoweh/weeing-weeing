import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'
import './layout.scss'
export default function AppShell({ theme, onToggleTheme, user, onLogin, onLogout, children }) {
  return <div className="shell"><Header user={user} onLogin={onLogin} onLogout={onLogout} theme={theme} onToggleTheme={onToggleTheme} /><Sidebar /><main className="shell__content" id="main-content">{children}</main></div>
}
