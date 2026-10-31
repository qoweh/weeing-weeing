import { useCallback, useEffect, useState } from 'react'
import {
  currentUser,
  loginUser,
  logoutUser,
  setAccessToken,
} from './api/client'
import AppShell from './components/layout/AppShell.jsx'
// 기존 대시보드는 src/views/DashboardPage.jsx에 보관한다. 복구 시 아래 주석을 푼다.
// import DashboardPage from './views/DashboardPage.jsx'
import PreparingPage from './views/PreparingPage.jsx'
import LoginPage from './views/LoginPage.jsx'
import { ManualPage, ManualUploadPage } from './views/ManualPages.jsx'
import IncidentsPage from './views/IncidentsPage.jsx'
import MaintenancePage from './views/MaintenancePage.jsx'
import ReportDraftModal from './components/report/ReportDraftModal.jsx'
import SignupPage from './views/SignupPage.jsx'

const sessionKey = 'weeing-report-session'
const historyKey = 'weeing-app-view'
const pages = new Set([
  'dashboard',
  'manuals',
  'manual-upload',
  'maintenance',
  'incidents',
])

function readHistoryView() {
  if (typeof window === 'undefined') return null
  const view = window.history.state?.[historyKey]
  return view && pages.has(view.page) ? view : null
}

function writeHistoryView(view, replace = false) {
  if (typeof window === 'undefined') return
  const state = { ...(window.history.state || {}), [historyKey]: view }
  const method = replace ? 'replaceState' : 'pushState'
  window.history[method](state, '', window.location.href)
}

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
  const [initialView] = useState(
    () => readHistoryView() || { page: 'dashboard', reportSelection: null },
  )
  const [reportSelection, setReportSelection] = useState(
    initialView.reportSelection || null,
  )
  const [page, setPage] = useState(initialView.page)
  const [maintenanceRefreshKey, setMaintenanceRefreshKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const forgetSession = useCallback(() => {
    setAccessToken('')
    sessionStorage.removeItem(sessionKey)
    setUser(null)
    setAuthPage('login')
    setPage('dashboard')
    setReportSelection(null)
    writeHistoryView({ page: 'dashboard', reportSelection: null }, true)
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
    if (!readHistoryView()) {
      writeHistoryView({ page, reportSelection }, true)
    }

    function restoreHistoryView() {
      const view = readHistoryView()
      setPage(view?.page || 'dashboard')
      setReportSelection(view?.reportSelection || null)
    }

    window.addEventListener('popstate', restoreHistoryView)
    return () => window.removeEventListener('popstate', restoreHistoryView)
  }, [])

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
    setPage('dashboard')
    setReportSelection(null)
    writeHistoryView({ page: 'dashboard', reportSelection: null }, true)
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

  const navigate = useCallback((nextPage) => {
    if (!pages.has(nextPage)) return
    const nextView = { page: nextPage, reportSelection: null }
    writeHistoryView(nextView)
    setPage(nextPage)
    setReportSelection(null)
  }, [])

  const openReportDraft = useCallback(
    (incident, reportId = '', row = null) => {
      const selectedIncident =
        incident ||
        (row?.incidentId ? { incident_id: row.incidentId } : null)
      if (!selectedIncident && !reportId) {
        setError('사건 정보를 찾을 수 없어 보고서를 열 수 없습니다.')
        return
      }

      const selection = {
        incident: selectedIncident,
        incidentId: selectedIncident?.incident_id || '',
        reportId,
      }

      const origin = page === 'incidents' ? 'incidents' : 'maintenance'
      if (page !== origin) {
        writeHistoryView({ page: origin, reportSelection: null })
      }
      const nextView = { page: origin, reportSelection: selection }
      writeHistoryView(nextView)
      setPage(origin)
      setReportSelection(selection)
      setError('')
    },
    [page],
  )

  const closeReportDraft = useCallback(() => {
    if (readHistoryView()?.reportSelection) {
      window.history.back()
      return
    }
    const origin = page === 'incidents' ? 'incidents' : 'maintenance'
    const nextView = { page: origin, reportSelection: null }
    writeHistoryView(nextView, true)
    setPage(origin)
    setReportSelection(null)
  }, [page])

  function handleReportSaved() {
    setMaintenanceRefreshKey((key) => key + 1)
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
      onNavigate={navigate}
      onIncidentSelect={(incident) => openReportDraft(incident)}
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
        {/* <DashboardPage /> */}
        <PreparingPage onNavigate={navigate} />
      </div>
      {page === 'manuals' && (
        <ManualPage
          user={user}
          onNavigate={navigate}
          onSessionExpired={forgetSession}
          onBusyChange={setBusy}
        />
      )}
      {page === 'manual-upload' && (
        <ManualUploadPage
          onNavigate={navigate}
          onSessionExpired={forgetSession}
          onBusyChange={setBusy}
        />
      )}
      {page === 'maintenance' && (
        <MaintenancePage
          user={user}
          onSessionExpired={forgetSession}
          refreshKey={maintenanceRefreshKey}
          onOpen={(reportId, _incidentId, row) =>
            openReportDraft(
              row?.incident,
              reportId,
              row,
            )
          }
        />
      )}
      {page === 'incidents' && (
        <IncidentsPage
          onSessionExpired={forgetSession}
          refreshKey={maintenanceRefreshKey}
          onOpen={(reportId, _incidentId, row) =>
            openReportDraft(row?.incident, reportId, row)
          }
        />
      )}
      {reportSelection && (
        <ReportDraftModal
          key={`${reportSelection.incidentId}:${reportSelection.reportId || 'new'}`}
          incident={reportSelection.incident}
          reportId={reportSelection.reportId}
          user={user}
          onClose={closeReportDraft}
          onSaved={handleReportSaved}
          onSessionExpired={forgetSession}
        />
      )}
    </AppShell>
  )
}
