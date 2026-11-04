import { useEffect, useRef, useState } from 'react'
import { listIncidents } from '../../api/client'
import Button from '../ui/Button.jsx'

export default function Header({ theme, onToggleTheme, user, onLogout, busy, onIncidentSelect, onSessionExpired }) {
  const [incidents, setIncidents] = useState(null)
  const [level, setLevel] = useState('')
  const [error, setError] = useState('')
  const panel = useRef(null)
  useEffect(() => {
    let active = true, pending = false, again = false
    async function refresh() {
      if (pending) { again = true; return }
      pending = true
      try {
        const rows = await listIncidents()
        if (active) { setIncidents(rows.filter((item) => ['OPEN', 'ACKNOWLEDGED'].includes(item.status))); setError('') }
      } catch (failure) {
        if (active) { setError(failure.message); setIncidents(null); if (failure.status === 401) onSessionExpired() }
      } finally {
        pending = false
        if (again && active) { again = false; refresh() }
      }
    }
    refresh()
    const timer = setInterval(refresh, 30000)
    window.addEventListener('weeing:incidents-changed', refresh)
    return () => { active = false; clearInterval(timer); window.removeEventListener('weeing:incidents-changed', refresh) }
  }, [onSessionExpired])
  useEffect(() => {
    if (!level) return
    function outside(event) { if (!panel.current?.contains(event.target)) setLevel('') }
    function escape(event) { if (event.key === 'Escape') setLevel('') }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [level])
  const items = incidents?.filter((item) => item.severity === level) || []
  return <header className="header"><a className="brand" href="#main-content"><span className="brand__mark">W</span><span>위잉위잉<small>Equipment AI</small></span></a><div className="header__main"><div className="header-alerts" ref={panel}>
    {[["Warning", "주의"], ["Error", "경고"]].map(([value, label]) => <button type="button" key={value} className={`header-alert header-alert--${value}`} aria-expanded={level === value} aria-controls="header-alert-popup" onClick={() => setLevel((current) => current === value ? '' : value)}><span>{value === 'Warning' ? '△' : '◈'} {label}</span><b>{incidents ? incidents.filter((item) => item.severity === value).length : '—'}</b></button>)}
    {level && <section className="header-alert-popup" id="header-alert-popup" aria-label={`${level === 'Warning' ? '주의' : '경고'} 사건 목록`}><div className="header-alert-popup__heading"><strong>{level === 'Warning' ? '주의' : '경고'} 사건</strong><button type="button" aria-label="닫기" onClick={() => setLevel('')}>×</button></div><p>진행 중인 최근 사건 · 30초마다 갱신</p>{error ? <p role="alert">{error}</p> : incidents === null ? <p>불러오는 중입니다.</p> : items.length === 0 ? <p>진행 중인 사건이 없습니다.</p> : <div className="header-alert-popup__scroll"><table><thead><tr><th>설비</th><th>에러 번호</th><th>발생 시각</th></tr></thead><tbody>{items.map((item) => <tr key={item.incident_id}><td>{item.asset_id}</td><td>{level === 'Error' ? <button type="button" className="header-alert-popup__link" onClick={() => { setLevel(''); onIncidentSelect(item.incident_id) }}>{item.codes.join(', ')}</button> : item.codes.join(', ')}</td><td>{new Date(item.first_detected_at).toLocaleString('ko-KR')}</td></tr>)}</tbody></table></div>}</section>}
  </div><div className="header__actions"><Button iconOnly onClick={onToggleTheme} aria-label={theme === 'light' ? '다크 모드로 전환' : '라이트 모드로 전환'}><span aria-hidden="true">{theme === 'light' ? '☾' : '☀'}</span></Button>{user && <><div className="header__profile"><span className="header__avatar" aria-hidden="true">W</span><span>{user.name}<small>{user.role}</small></span></div><Button onClick={onLogout} disabled={busy}>로그아웃</Button></>}</div></div></header>
}
