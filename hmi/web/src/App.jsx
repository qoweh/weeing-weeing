import { useCallback, useEffect, useState } from 'react'
import { currentUser, getReport, loginUser, logoutUser, setAccessToken } from './api/client'
import AppShell from './components/layout/AppShell.jsx'
import RagWorkspace from './components/RagWorkspace.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import MaintenancePage from './pages/MaintenancePage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import SignupPage from './pages/SignupPage.jsx'

const sessionKey = 'weeing-report-session'

function initialTheme() {
  try {
    const saved = localStorage.getItem('weeing-theme')
    if (saved === 'light' || saved === 'dark') return saved
  } catch { /* Storage may be unavailable. */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [theme, setTheme] = useState(initialTheme)
  const [authPage, setAuthPage] = useState('login')
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(() => Boolean(sessionStorage.getItem(sessionKey)))
  const [page, setPage] = useState(() => sessionStorage.getItem('weeing-document-completed') ? 'documents' : 'dashboard')
  const [reportSelection, setReportSelection] = useState({ key: 0 })
  const [maintenanceTab, setMaintenanceTab] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const forgetSession = useCallback(() => {
    setAccessToken('')
    sessionStorage.removeItem(sessionKey)
    setUser(null)
    setAuthPage('login')
    setPage('dashboard')
    setMaintenanceTab(null)
  }, [])

  useEffect(() => { window.scrollTo(0, 0) }, [page])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('weeing-theme', theme) } catch { /* Theme still works for this session. */ }
  }, [theme])

  useEffect(() => {
    const token = sessionStorage.getItem(sessionKey)
    if (!token) return
    let cancelled = false
    setAccessToken(token)
    currentUser().then((account) => {
      if (!cancelled) setUser(account)
    }).catch((failure) => {
      if (cancelled) return
      if (failure.status === 401) forgetSession()
      setError(failure.message)
    }).finally(() => { if (!cancelled) setChecking(false) })
    return () => { cancelled = true }
  }, [forgetSession])

  async function login(employeeNo, password) {
    const session = await loginUser(employeeNo, password)
    sessionStorage.setItem(sessionKey, session.access_token)
    setAccessToken(session.access_token)
    setError('')
    setUser(session.user)
  }

  async function openMaintenanceReport(reportId, incidentId, version) {
    setBusy(true)
    setError('')
    try {
      const document = reportId ? await getReport(reportId, version) : null
      setReportSelection((previous) => ({ key: previous.key + 1, document, incidentId }))
      setPage('report-write')
    } catch (failure) {
      if (failure.status === 401) forgetSession()
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await logoutUser()
      forgetSession()
    } catch (failure) {
      if (failure.status === 401) forgetSession()
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  if (checking) return <main className="login-page"><p role="status">로그인 상태를 확인하고 있습니다.</p></main>
  if (!user) return authPage === 'signup'
    ? <SignupPage onLogin={() => setAuthPage('login')} />
    : <LoginPage onLogin={login} onSignup={() => setAuthPage('signup')} error={error} />

  return <AppShell user={user} onLogout={logout} busy={busy} page={page} onNavigate={setPage}
    theme={theme} onToggleTheme={() => setTheme((current) => current === 'light' ? 'dark' : 'light')}>
    {error && <p className="workspace-error" role="alert">{error}</p>}
    <div hidden={page !== 'dashboard'}><DashboardPage /></div>
    {page === 'maintenance' && <MaintenancePage user={user} busy={busy} selectedTab={maintenanceTab} onSelectTab={setMaintenanceTab} onOpen={openMaintenanceReport} onSessionExpired={forgetSession} />}
    <div hidden={page === 'dashboard' || page === 'maintenance'}>
      <RagWorkspace tab={page} user={user} onSessionExpired={forgetSession} onBusyChange={setBusy} workspaceBusy={busy} onNavigate={setPage} reportSelection={reportSelection} />
    </div>
  </AppShell>
}
