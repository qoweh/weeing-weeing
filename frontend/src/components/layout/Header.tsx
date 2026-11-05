import { useEffect, useRef, useState } from 'react'
import { listIncidents, watchTelemetry, type Incident } from '../../api/client'
import Button from '../ui/Button'
import { dateLabel } from '../ui/library'
import SettingsDialog from './SettingsDialog'
import type { Settings } from './settings'

export default function Header({
  theme,
  onToggleTheme,
  user,
  onLogout,
  busy,
  screenZoom,
  onChangeScreenZoom,
  defaultScreenZoom,
  onResetScreenZoom,
  sidebarCollapsed,
  onChangeSidebarCollapsed,
  onIncidentSelect,
  onNavigateDashboard,
  onSessionExpired,
  settings,
  onChangeSettings,
}: {
  theme: string
  onToggleTheme: () => void
  user: { name: string; role: string; employee_no: string }
  onLogout: () => void
  busy: boolean
  screenZoom: number
  onChangeScreenZoom: (value: number | ((value: number) => number)) => void
  defaultScreenZoom: number
  onResetScreenZoom: () => void
  sidebarCollapsed: boolean
  onChangeSidebarCollapsed: (value: boolean) => void
  onIncidentSelect: (incident: Incident) => void
  onNavigateDashboard: () => void
  onSessionExpired: () => void
  settings: Settings
  onChangeSettings: (settings: Settings) => void
}) {
  const [incidents, setIncidents] = useState<Incident[] | null>(null),
    [error, setError] = useState(''),
    [severity, setSeverity] = useState<'Warning' | 'Error' | null>(null)
  const [popupPosition, setPopupPosition] = useState<{
    top: number
    right: number
    maxWidth: number
  } | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const knownIncidents = useRef<Set<string> | null>(null)
  const autoOpenError = useRef(false)
  autoOpenError.current = settings.autoOpenError && settings.notifyError
  const alertButtons = useRef<Record<string, HTMLButtonElement | null>>({})
  const alertPopup = useRef<HTMLElement>(null)
  const accountMenu = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    function closeOnOutsidePointer(event: PointerEvent) {
      const menu = accountMenu.current
      if (
        menu?.open &&
        event.target instanceof Node &&
        !menu.contains(event.target)
      )
        menu.open = false
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    return () =>
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
  }, [])
  useEffect(() => {
    let active = true
    let pending: ReturnType<typeof setTimeout> | undefined
    let retry: ReturnType<typeof setTimeout> | undefined
    let lastRefresh = 0
    let lastIncidents = ''
    const controller = new AbortController()
    async function refresh() {
      try {
        const rows = await listIncidents()
        if (active) {
          const open = rows.filter((r) =>
            ['OPEN', 'ACKNOWLEDGED'].includes(r.status),
          )
          // 새 경고가 들어오면(설정한 경우) 경고 사건 팝업을 바로 연다.
          const known = knownIncidents.current
          if (
            known &&
            autoOpenError.current &&
            open.some(
              (r) => r.severity === 'Error' && !known.has(r.incident_id),
            )
          )
            setSeverity('Error')
          knownIncidents.current = new Set(open.map((r) => r.incident_id))
          setIncidents(open)
          setError('')
        }
      } catch (e) {
        if (active) {
          setError(
            e instanceof Error ? e.message : '사건을 불러오지 못했습니다.',
          )
          setIncidents([])
        }
      }
    }
    refresh()
    function scheduleRefresh() {
      if (pending) return
      pending = setTimeout(
        () => {
          pending = undefined
          lastRefresh = Date.now()
          void refresh()
          window.dispatchEvent(new Event('weeing-incidents-changed'))
        },
        Math.max(0, settings.refreshInterval - (Date.now() - lastRefresh)),
      )
    }
    async function connect() {
      try {
        await watchTelemetry(controller.signal, (state) => {
          const current = JSON.stringify(state.incidents)
          if (current !== lastIncidents) {
            lastIncidents = current
            scheduleRefresh()
          }
          if (
            state.db_status === 'storage_failed' ||
            state.db_status === 'not_connected'
          ) {
            // The incident list is DB-backed; a live event alone does not prove persistence.
            if (state.db_status === 'storage_failed')
              setError('센서 사건을 DB에 저장하지 못했습니다.')
          }
        })
      } catch (e) {
        if (!active) return
        if (e && typeof e === 'object' && 'status' in e && e.status === 401) {
          onSessionExpired()
          return
        }
        setError('실시간 연결이 끊어져 재연결 중입니다.')
      }
      if (active) retry = setTimeout(connect, 3000)
    }
    void connect()
    return () => {
      active = false
      controller.abort()
      clearTimeout(pending)
      clearTimeout(retry)
    }
  }, [settings.refreshInterval, onSessionExpired])
  useEffect(() => {
    if (!severity) return
    function positionPopup() {
      const rect = alertButtons.current[severity!]?.getBoundingClientRect()
      if (!rect) return
      const scale = screenZoom / 100
      const right = Math.max(16 * scale, window.innerWidth - rect.right)
      setPopupPosition({
        top: rect.bottom / scale + 8,
        right: right / scale,
        maxWidth: Math.max(0, (window.innerWidth - right) / scale - 16),
      })
    }
    function dismiss(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !alertPopup.current?.contains(event.target) &&
        !alertButtons.current[severity!]?.contains(event.target)
      )
        setSeverity(null)
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setSeverity(null)
        alertButtons.current[severity!]?.focus()
      }
    }
    positionPopup()
    window.addEventListener('resize', positionPopup)
    window.addEventListener('scroll', positionPopup, true)
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', handleKey)
    return () => {
      window.removeEventListener('resize', positionPopup)
      window.removeEventListener('scroll', positionPopup, true)
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', handleKey)
    }
  }, [severity, screenZoom])
  return (
    <header className="header">
      <button type="button" className="brand" aria-label="대시보드로 이동" disabled={busy} onClick={onNavigateDashboard}>
        <span className="brand__mark"><img src="/assets/IMAGE/weeing-logo.png" alt="" /></span>
        <span>
          위잉위잉<small>Equipment AI</small>
        </span>
      </button>
      <div className="header__main">
        <div className="header__actions">
          {(
            [
              ['Warning', '주의', '513bd', settings.notifyWarning],
              ['Error', '경고', '24639', settings.notifyError],
            ] as ['Warning' | 'Error', string, string, boolean][]
          )
            .filter((item) => item[3])
            .map(([level, label, icon]) => (
              <Button
                key={level}
                ref={(element) => {
                  alertButtons.current[level] = element
                }}
                className={`header-alert header-alert--${level}`}
                onClick={() => {
                  setSeverity((current) => (current === level ? null : level))
                }}
                aria-label={`${label} 사건 보기`}
                aria-expanded={severity === level}
                aria-controls="header-alert-popup"
              >
                <img src={`/assets/ICONS/${icon}.svg`} alt="" />
                <span>{label}</span>
                <b>
                  {incidents
                    ? incidents.filter((i) => i.severity === level).length
                    : '—'}
                </b>
              </Button>
            ))}
          {user && (
            <details className="header-account" ref={accountMenu}>
              <summary aria-label="내 계정" title={user.name}>
                <span className="header__avatar">W</span>
                <span className="header-account__summary-text">
                  <strong>{user.name}</strong>
                  <small>{user.role}</small>
                </span>
              </summary>
              <div className="header-account__menu">
                <div className="header-account__identity">
                  <strong>{user.name}</strong>
                  <p>{user.role}</p>
                </div>
                <div className="header-account__section">
                  <button
                    type="button"
                    className="header-account__item"
                    onClick={() => {
                      if (accountMenu.current) accountMenu.current.open = false
                      setSettingsOpen(true)
                    }}
                  >
                    <span className="header-account__item-label">
                      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path
                          d="M10.3 2.8h3.4l.5 2.2c.5.2 1 .4 1.4.6l1.9-1.2 2.4 2.4-1.2 1.9c.2.4.4.9.6 1.4l2.2.5v3.4l-2.2.5c-.2.5-.4 1-.6 1.4l1.2 1.9-2.4 2.4-1.9-1.2c-.4.2-.9.4-1.4.6l-.5 2.2h-3.4l-.5-2.2c-.5-.2-1-.4-1.4-.6l-1.9 1.2-2.4-2.4 1.2-1.9c-.2-.4-.4-.9-.6-1.4l-2.2-.5v-3.4l2.2-.5c.2-.5.4-1 .6-1.4L4.1 6.8l2.4-2.4 1.9 1.2c.4-.2.9-.4 1.4-.6l.5-2.2Z"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinejoin="round"
                        />
                        <circle
                          cx="12"
                          cy="12"
                          r="3"
                          stroke="currentColor"
                          strokeWidth="1.5"
                        />
                      </svg>
                      설정
                    </span>
                    <span
                      className="header-account__item-note"
                      aria-hidden="true"
                    >
                      ›
                    </span>
                  </button>
                </div>
                <div className="header-account__section">
                  <button
                    type="button"
                    className="header-account__item header-account__item--logout"
                    onClick={onLogout}
                    disabled={busy}
                  >
                    로그아웃
                  </button>
                </div>
              </div>
            </details>
          )}
        </div>
      </div>
      {severity && popupPosition && (
        <section
          id="header-alert-popup"
          ref={alertPopup}
          className="header-alert-popup"
          style={popupPosition}
          aria-label={`${severity === 'Warning' ? '주의' : '경고'} 사건 요약`}
        >
          <div className="header-alert-popup__heading">
            <h2>{severity === 'Warning' ? '주의' : '경고'} 사건</h2>
            <span>진행 중인 사건 기준</span>
          </div>
          <div
            className="header-alert-popup__scroll"
            role="region"
            aria-label="주의 및 경고 사건 표"
            tabIndex={0}
          >
            <table className="header-alert-popup__table">
              <thead>
                <tr>
                  {['번호', '적용 설비', '에러 번호', '경고 발생일'].map(
                    (label) => (
                      <th scope="col" key={label}>
                        {label}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {incidents === null ||
                !incidents.some((i) => i.severity === severity) ? (
                  <tr>
                    <td colSpan={4} className="header-alert-popup__empty">
                      {incidents === null
                        ? '불러오는 중입니다.'
                        : '해당하는 진행 중 사건이 없습니다.'}
                    </td>
                  </tr>
                ) : (
                  incidents
                    .filter((i) => i.severity === severity)
                    .map((incident, index) => (
                      <tr
                        key={incident.incident_id}
                        className="header-alert-popup__clickable-row"
                        tabIndex={0}
                        onClick={(event) => {
                          if (
                            event.target instanceof Element &&
                            !event.target.closest('button')
                          ) {
                            setSeverity(null)
                            onIncidentSelect?.(incident)
                          }
                        }}
                        onKeyDown={(event) => {
                          if (
                            event.target === event.currentTarget &&
                            (event.key === 'Enter' || event.key === ' ')
                          ) {
                            event.preventDefault()
                            setSeverity(null)
                            onIncidentSelect?.(incident)
                          }
                        }}
                      >
                        <td>{String(index + 1).padStart(2, '0')}</td>
                        <td>{incident.asset_id || '—'}</td>
                        <td>
                          <button
                            type="button"
                            className="header-alert-popup__incident-link"
                            onClick={() => {
                              setSeverity(null)
                              onIncidentSelect?.(incident)
                            }}
                          >
                            {incident.codes?.join(', ') || '사건 보고서 열기'}
                          </button>
                        </td>
                        <td>{dateLabel(incident.first_detected_at, true)}</td>
                      </tr>
                    ))
                )}
              </tbody>
            </table>
          </div>
          <p className="header-alert-popup__note">
            {error
              ? `사건 목록을 불러오지 못했습니다. ${error}`
              : '사건 변경 수신 시 설정한 주기로 갱신'}
          </p>
        </section>
      )}
      {settingsOpen && user && (
        <SettingsDialog
          user={user}
          theme={theme}
          onToggleTheme={onToggleTheme}
          screenZoom={screenZoom}
          onChangeScreenZoom={onChangeScreenZoom}
          defaultScreenZoom={defaultScreenZoom}
          onResetScreenZoom={onResetScreenZoom}
          sidebarCollapsed={sidebarCollapsed}
          onChangeSidebarCollapsed={onChangeSidebarCollapsed}
          settings={settings}
          onChangeSettings={onChangeSettings}
          onLogout={onLogout}
          busy={busy}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </header>
  )
}
