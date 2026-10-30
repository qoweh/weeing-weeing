import { useEffect, useRef, useState } from 'react'
import { listIncidents } from '../../api/client'
import Button from '../ui/Button.jsx'
import { dateLabel } from '../ui/library'

export default function Header({ theme, onToggleTheme, user, onLogout, busy, screenZoom, onChangeScreenZoom }) {
  const [incidents, setIncidents] = useState(null),
    [error, setError] = useState(''),
    [severity, setSeverity] = useState(null)
  const [popupPosition, setPopupPosition] = useState(null)
  const alertButtons = useRef({})
  const alertPopup = useRef(null)
  useEffect(() => {
    let active = true
    async function refresh() {
      try {
        const rows = await listIncidents()
        if (active) {
          setIncidents(
            rows.filter((r) => ['OPEN', 'ACKNOWLEDGED'].includes(r.status)),
          )
          setError('')
        }
      } catch (e) {
        if (active) {
          setIncidents(null)
          setError(e.message)
        }
      }
    }
    refresh()
    const timer = setInterval(refresh, 30000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [])
  useEffect(() => {
    if (!severity) return
    function positionPopup() {
      const rect = alertButtons.current[severity]?.getBoundingClientRect()
      if (!rect) return
      const scale = screenZoom / 100
      const right = Math.max(16 * scale, window.innerWidth - rect.right)
      setPopupPosition({ top: rect.bottom / scale + 8, right: right / scale, maxWidth: Math.max(0, (window.innerWidth - right) / scale - 16) })
    }
    function dismiss(event) {
      if (!alertPopup.current?.contains(event.target) && !alertButtons.current[severity]?.contains(event.target)) setSeverity(null)
    }
    function handleKey(event) {
      if (event.key === 'Escape') {
        setSeverity(null)
        alertButtons.current[severity]?.focus()
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
      <a className="brand" href="#main-content">
        <span className="brand__mark">W</span>
        <span>
          위잉위잉<small>Equipment AI</small>
        </span>
      </a>
      <div className="header__main">
        <div className="header__actions">
          {[
            ['Warning', '주의', '513bd'],
            ['Error', '경고', '24639'],
          ].map(([level, label, icon]) => (
            <Button
              key={level}
              ref={(element) => { alertButtons.current[level] = element }}
              className={`header-alert header-alert--${level}`}
              onClick={() => {
                setSeverity((current) => current === level ? null : level)
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
            <details className="header-account">
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
                  <div className="header-account__zoom">
                    <span>비율조정</span>
                    <div className="header-account__zoom-controls" role="group" aria-label="화면 확대 및 축소">
                      <button type="button" aria-label="화면 축소" disabled={screenZoom <= 80} onClick={() => onChangeScreenZoom((value) => Math.max(80, value - 10))}>−</button>
                      <button type="button" className="header-account__zoom-reset" aria-label={`현재 ${screenZoom}%, 화면 비율 100%로 초기화`} onClick={() => onChangeScreenZoom(100)}>{screenZoom}%</button>
                      <button type="button" aria-label="화면 확대" disabled={screenZoom >= 140} onClick={() => onChangeScreenZoom((value) => Math.min(140, value + 10))}>+</button>
                    </div>
                  </div>
                </div>
                <div className="header-account__section">
                  <button type="button" className="header-account__item" disabled>
                    <span className="header-account__item-label">
                      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M10.3 2.8h3.4l.5 2.2c.5.2 1 .4 1.4.6l1.9-1.2 2.4 2.4-1.2 1.9c.2.4.4.9.6 1.4l2.2.5v3.4l-2.2.5c-.2.5-.4 1-.6 1.4l1.2 1.9-2.4 2.4-1.9-1.2c-.4.2-.9.4-1.4.6l-.5 2.2h-3.4l-.5-2.2c-.5-.2-1-.4-1.4-.6l-1.9 1.2-2.4-2.4 1.2-1.9c-.2-.4-.4-.9-.6-1.4l-2.2-.5v-3.4l2.2-.5c.2-.5.4-1 .6-1.4L4.1 6.8l2.4-2.4 1.9 1.2c.4-.2.9-.4 1.4-.6l.5-2.2Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                        <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.5" />
                      </svg>
                      설정
                    </span>
                    <span className="header-account__item-note">준비 중</span>
                  </button>
                </div>
                <div className="header-account__section">
                  <button
                    type="button"
                    className="header-account__item"
                    onClick={onToggleTheme}
                    aria-label={`테마변경: ${theme === 'light' ? '다크 모드로 전환' : '라이트 모드로 전환'}`}
                  >
                    <span className="header-account__item-label">
                      {theme === 'light' ? (
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                          <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.5" />
                          <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42m0-14.14-1.42 1.42M6.35 17.65l-1.42 1.42" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                        </svg>
                      ) : (
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                          <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                      테마변경
                    </span>
                    <span className="header-account__item-note">{theme === 'light' ? '라이트' : '다크'}</span>
                  </button>
                </div>
                <div className="header-account__section">
                  <button type="button" className="header-account__item header-account__item--logout" onClick={onLogout} disabled={busy}>
                    로그아웃
                  </button>
                </div>
              </div>
            </details>
          )}
        </div>
      </div>
      {severity && popupPosition && (
        <section id="header-alert-popup" ref={alertPopup} className="header-alert-popup" style={popupPosition} aria-label={`${severity === 'Warning' ? '주의' : '경고'} 사건 요약`}>
          <div className="header-alert-popup__heading">
            <h2>{severity === 'Warning' ? '주의' : '경고'} 사건</h2>
            <span>진행 중인 사건 기준</span>
          </div>
          <div className="header-alert-popup__scroll" role="region" aria-label="주의 및 경고 사건 표" tabIndex={0}>
            <table className="header-alert-popup__table">
              <thead><tr>{['번호', '적용 설비', '에러 번호', '경고 발생일'].map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead>
              <tbody>
                {error || incidents === null || !incidents.some((i) => i.severity === severity) ? (
                  <tr><td colSpan={4} className="header-alert-popup__empty">{error ? `사건을 불러오지 못했습니다: ${error}` : incidents === null ? '불러오는 중입니다.' : '해당하는 진행 중 사건이 없습니다.'}</td></tr>
                ) : incidents.filter((i) => i.severity === severity).map((incident, index) => (
                  <tr key={incident.incident_id}>
                    <td>{String(index + 1).padStart(2, '0')}</td>
                    <td>{incident.asset_id || '—'}</td>
                    <td>{incident.codes?.join(', ') || '—'}</td>
                    <td>{dateLabel(incident.first_detected_at, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="header-alert-popup__note">최근 조회된 사건 기준 · 30초마다 갱신</p>
        </section>
      )}
    </header>
  )
}
