import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import AppShell from './components/layout/AppShell'
import DashboardPage from './views/DashboardPage'
import LoginPage from './views/LoginPage'
import SignupPage from './views/SignupPage'

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
  const [authPage, setAuthPage] = useState<'login' | 'signup'>('login')
  const [authTransition, setAuthTransition] = useState(false)
  const [authExiting, setAuthExiting] = useState(false)
  const transitionTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  )
  const authCard = useRef<HTMLElement>(null)
  const targetCard = useRef<HTMLElement>(null)
  useEffect(() => () => clearTimeout(transitionTimer.current), [])
  const [user, setUser] = useState(() => {
    try {
      return localStorage.getItem('weeing-demo-login') === 'true'
        ? { name: '사용자 1' }
        : null
    } catch {
      return null
    }
  })
  useLayoutEffect(() => {
    const card = authCard.current
    const target = targetCard.current
    if (!authExiting || !card || !target) return
    const previousHeight = card.getBoundingClientRect().height
    const nextHeight = target.getBoundingClientRect().height
    const animation = card.animate(
      [
        {
          height: `${previousHeight}px`,
          boxSizing: 'border-box',
          overflow: 'hidden',
        },
        {
          height: `${nextHeight}px`,
          boxSizing: 'border-box',
          overflow: 'hidden',
        },
      ],
      {
        duration: 350,
        easing: 'cubic-bezier(.22, 1.3, .36, 1)',
        fill: 'forwards',
      },
    )
    return () => animation.cancel()
  }, [authExiting])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('weeing-theme', theme)
    } catch {
      /* Theme still works for this session. */
    }
  }, [theme])
  useEffect(() => {
    function syncLogin(event: StorageEvent) {
      if (event.key === 'weeing-demo-login' || event.key === null) {
        setUser(
          event.key === 'weeing-demo-login' && event.newValue === 'true'
            ? { name: '사용자 1' }
            : null,
        )
      }
    }
    window.addEventListener('storage', syncLogin)
    return () => window.removeEventListener('storage', syncLogin)
  }, [])
  function login() {
    try {
      localStorage.setItem('weeing-demo-login', 'true')
    } catch {
      /* Login remains active until the page is reloaded. */
    }
    setUser({ name: '사용자 1' })
  }
  function logout() {
    clearTimeout(transitionTimer.current)
    setAuthExiting(false)
    try {
      localStorage.removeItem('weeing-demo-login')
    } catch {
      /* Storage may be unavailable. */
    }
    setAuthPage('login')
    setAuthTransition(false)
    setUser(null)
  }
  function changeAuthPage(page: 'login' | 'signup') {
    if (authExiting) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setAuthTransition(false)
      setAuthPage(page)
      return
    }
    setAuthExiting(true)
    transitionTimer.current = setTimeout(() => {
      setAuthTransition(true)
      setAuthPage(page)
      setAuthExiting(false)
    }, 350)
  }
  if (!user)
    return (
      <>
        {authPage === 'signup' ? (
          <SignupPage
            cardRef={authCard}
            animate={authTransition}
            exiting={authExiting}
            onLogin={() => changeAuthPage('login')}
          />
        ) : (
          <LoginPage
            cardRef={authCard}
            animate={authTransition}
            exiting={authExiting}
            onLogin={login}
            onSignup={() => changeAuthPage('signup')}
          />
        )}
        {authExiting && (
          <div className="auth-measure" aria-hidden="true" inert>
            {authPage === 'login' ? (
              <SignupPage cardRef={targetCard} />
            ) : (
              <LoginPage cardRef={targetCard} />
            )}
          </div>
        )}
      </>
    )
  return (
    <AppShell
      user={user}
      onLogout={logout}
      theme={theme}
      onToggleTheme={() =>
        setTheme((current) => (current === 'light' ? 'dark' : 'light'))
      }
    >
      <DashboardPage />
    </AppShell>
  )
}
