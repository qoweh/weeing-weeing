import { useEffect, useState } from 'react'
import AppShell from './components/layout/AppShell.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import LoginPage from './pages/LoginPage.jsx'

function initialTheme() {
  try {
    const saved = localStorage.getItem('weeing-theme')
    if (saved === 'light' || saved === 'dark') return saved
  } catch { /* Storage may be unavailable. */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [theme, setTheme] = useState(initialTheme)
  const [user, setUser] = useState(() => {
    try { return localStorage.getItem('weeing-demo-login') === 'true' ? { name: '사용자 1' } : null } catch { return null }
  })
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('weeing-theme', theme) } catch { /* Theme still works for this session. */ }
  }, [theme])
  useEffect(() => {
    function syncLogin(event) {
      if (event.key === 'weeing-demo-login' || event.key === null) {
        setUser(event.key === 'weeing-demo-login' && event.newValue === 'true' ? { name: '사용자 1' } : null)
      }
    }
    window.addEventListener('storage', syncLogin)
    return () => window.removeEventListener('storage', syncLogin)
  }, [])
  function login() {
    try { localStorage.setItem('weeing-demo-login', 'true') } catch { /* Login remains active until the page is reloaded. */ }
    setUser({ name: '사용자 1' })
  }
  function logout() {
    try { localStorage.removeItem('weeing-demo-login') } catch { /* Storage may be unavailable. */ }
    setUser(null)
  }
  if (!user) return <LoginPage onLogin={login} />
  return <AppShell user={user} onLogout={logout} theme={theme} onToggleTheme={() => setTheme((current) => current === 'light' ? 'dark' : 'light')}><DashboardPage /></AppShell>
}
