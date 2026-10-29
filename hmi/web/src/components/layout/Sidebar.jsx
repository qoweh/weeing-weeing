const navigation = [
  { icon: '▦', label: '대시보드', id: 'dashboard' },
  { icon: '◉', label: '이상 사건', id: 'incidents', pending: true },
  { icon: '▤', label: '정비 보고서', id: 'report-write' },
  { icon: '⌕', label: '문서 검색', id: 'search', pending: true },
  { icon: '↥', label: '문서 등록', id: 'documents' },
  { icon: '✦', label: '에러 분석', id: 'analysis' },
]

export default function Sidebar({ page, onNavigate, busy }) {
  return <aside className="sidebar"><div className="sidebar__label">WORKSPACE</div>
    <nav aria-label="주 메뉴">{navigation.map(({ icon, label, id, pending }) => pending
      ? <span key={id} className="nav-item nav-item--disabled" title="준비 중"><span aria-hidden="true">{icon}</span>{label}<small>준비 중</small></span>
      : <button key={id} type="button" className={`nav-item ${page === id ? 'nav-item--active' : ''}`}
          aria-current={page === id ? 'page' : undefined} disabled={busy} onClick={() => onNavigate(id)}>
          <span aria-hidden="true">{icon}</span>{label}
        </button>)}</nav>
    <div className="sidebar__bottom"><div className="sidebar__notice"><span className="sidebar__notice-icon">✦</span><strong>근거 기반 설비 관리</strong><p>설비 정보를 한눈에 확인하고 필요한 근거를 살펴보세요.</p></div><p className="sidebar__caption">위잉위잉 · 설비 관리</p></div>
  </aside>
}
