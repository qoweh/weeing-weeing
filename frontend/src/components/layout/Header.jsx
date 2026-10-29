import { useEffect, useRef, useState } from 'react'
import { listIncidents } from '../../api/client'
import Button from '../ui/Button.jsx'
export default function Header({ theme, onToggleTheme, user, onLogout, busy }) {
  const [incidents, setIncidents] = useState(null),
    [error, setError] = useState(''),
    [severity, setSeverity] = useState('Warning')
  const dialog = useRef(null)
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
              className={`header-alert header-alert--${level}`}
              onClick={() => {
                setSeverity(level)
                dialog.current.showModal()
              }}
              aria-label={`${label} 사건 보기`}
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
          <Button
            iconOnly
            onClick={onToggleTheme}
            aria-label={
              theme === 'light' ? '다크 모드로 전환' : '라이트 모드로 전환'
            }
          >
            <span aria-hidden="true">{theme === 'light' ? '☾' : '☼'}</span>
          </Button>
          {user && (
            <details className="header-account">
              <summary aria-label="내 계정" title={user.name}>
                <span className="header__avatar">W</span>
              </summary>
              <div className="header-account__menu">
                <strong>{user.name}</strong>
                <p>{user.role}</p>
                <Button onClick={onLogout} disabled={busy}>
                  로그아웃
                </Button>
              </div>
            </details>
          )}
        </div>
      </div>
      <dialog ref={dialog} className="library-dialog">
        <form method="dialog">
          <Button>닫기</Button>
        </form>
        <h2>{severity === 'Warning' ? '주의' : '경고'} 사건</h2>
        <p>최근 조회된 사건 기준 · 30초마다 갱신</p>
        {error ? (
          <p role="alert">{error}</p>
        ) : incidents === null ? (
          <p>불러오는 중입니다.</p>
        ) : incidents.filter((i) => i.severity === severity).length ? (
          <ul>
            {incidents
              .filter((i) => i.severity === severity)
              .map((i) => (
                <li key={i.incident_id}>
                  {i.asset_id} · {i.codes.join(', ')} · {i.incident_id}
                </li>
              ))}
          </ul>
        ) : (
          <p>해당하는 진행 중 사건이 없습니다.</p>
        )}
      </dialog>
    </header>
  )
}
