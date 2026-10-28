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
  const [page, setPage] = useState('dashboard')
  const [user, setUser] = useState(null)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('weeing-theme', theme) } catch { /* Theme still works for this session. */ }
  }, [theme])
  if (page === 'login') return <LoginPage onCancel={() => setPage('dashboard')} onLogin={() => { setUser({ name: '사용자 1' }); setPage('dashboard') }} />
  return <AppShell user={user} onLogin={() => setPage('login')} onLogout={() => setUser(null)} theme={theme} onToggleTheme={() => setTheme((current) => current === 'light' ? 'dark' : 'light')}><DashboardPage /></AppShell>
}
