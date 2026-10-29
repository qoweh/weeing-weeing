import { useCallback, useEffect, useState } from 'react'
import {
  currentUser,
  loginUser,
  logoutUser,
  setAccessToken,
} from './api/client'
import AppShell from './components/layout/AppShell.jsx'
import DashboardPage from './views/DashboardPage.jsx'
import LoginPage from './views/LoginPage.jsx'
import { ManualPage, ManualUploadPage } from './views/ManualPages.jsx'
import MaintenancePage from './views/MaintenancePage.jsx'
import ReportWorkspace from './components/report/ReportWorkspace.jsx'
import SignupPage from './views/SignupPage.jsx'

const sessionKey = 'weeing-report-session'

function initialTheme() {
  try {
    const saved = localStorage.getItem('weeing-theme')
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* Storage may be unavailable. */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

export default function App() {
  const [theme, setTheme] = useState(initialTheme)
  const [authPage, setAuthPage] = useState('login')
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(() =>
    Boolean(sessionStorage.getItem(sessionKey)),
  )
  const [reportSelection, setReportSelection] = useState({})
  const [page, setPage] = useState('dashboard')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const forgetSession = useCallback(() => {
    setAccessToken('')
    sessionStorage.removeItem(sessionKey)
    setUser(null)
    setAuthPage('login')
    setPage('dashboard')
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('weeing-theme', theme)
    } catch {
      /* Theme still works for this session. */
    }
  }, [theme])

  useEffect(() => {
    const token = sessionStorage.getItem(sessionKey)
    if (!token) return
    let cancelled = false
    setAccessToken(token)
    currentUser()
      .then((account) => {
        if (!cancelled) setUser(account)
      })
      .catch((failure) => {
        if (cancelled) return
        if (failure.status === 401) forgetSession()
        setError(failure.message)
      })
      .finally(() => {
        if (!cancelled) setChecking(false)
      })
    return () => {
      cancelled = true
    }
  }, [forgetSession])

  async function login(employeeNo, password) {
    const session = await loginUser(employeeNo, password)
    sessionStorage.setItem(sessionKey, session.access_token)
    setAccessToken(session.access_token)
    setError('')
    setUser(session.user)
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

  if (checking)
    return (
      <main className="login-page">
        <p role="status">로그인 상태를 확인하고 있습니다.</p>
      </main>
    )
  if (!user)
    return authPage === 'signup' ? (
      <SignupPage onLogin={() => setAuthPage('login')} />
    ) : (
      <LoginPage
        onLogin={login}
        onSignup={() => setAuthPage('signup')}
        error={error}
      />
    )

  return (
    <AppShell
      user={user}
      onLogout={logout}
      busy={busy}
      page={page}
      onNavigate={setPage}
      theme={theme}
      onToggleTheme={() =>
        setTheme((current) => (current === 'light' ? 'dark' : 'light'))
      }
    >
      {error && (
        <p className="workspace-error" role="alert">
          {error}
        </p>
      )}
      <div hidden={page !== 'dashboard'}>
        <DashboardPage />
      </div>
      {page === 'manuals' && (
        <ManualPage onNavigate={setPage} onSessionExpired={forgetSession} />
      )}
      {page === 'manual-upload' && (
        <ManualUploadPage
          onNavigate={setPage}
          onSessionExpired={forgetSession}
          onBusyChange={setBusy}
        />
      )}
      {page === 'maintenance' && (
        <MaintenancePage
          onSessionExpired={forgetSession}
          onOpen={(reportId, incidentId) => {
            setReportSelection({ reportId, incidentId })
            setPage('report-write')
          }}
        />
      )}
      {page === 'report-write' && (
        <>
          <button
            className="button"
            disabled={busy}
            onClick={() => setPage('maintenance')}
          >
            정비 이력 목록으로
          </button>
          <ReportWorkspace
            user={user}
            onSessionExpired={forgetSession}
            onBusyChange={setBusy}
            initialReportId={reportSelection.reportId}
            initialIncidentId={reportSelection.incidentId}
          />
        </>
      )}
    </AppShell>
  )
}
