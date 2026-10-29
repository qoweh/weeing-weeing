const navigation = [
  ['▦', '대시보드'],
  ['◉', '이상 사건'],
  ['▤', '정비 보고서'],
  ['⌕', '문서 검색'],
]
export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar__label">WORKSPACE</div>
      <nav aria-label="주 메뉴">
        {navigation.map(([icon, label], index) =>
          index === 0 ? (
            <a
              key={label}
              className="nav-item nav-item--active"
              href="#main-content"
              aria-current="page"
            >
              <span aria-hidden="true">{icon}</span>
              {label}
            </a>
          ) : (
            <span
              key={label}
              className="nav-item nav-item--disabled"
              title="준비 중"
            >
              <span aria-hidden="true">{icon}</span>
              {label}
              <small>준비 중</small>
            </span>
          ),
        )}
      </nav>
      <div className="sidebar__bottom">
        <div className="sidebar__notice">
          <span className="sidebar__notice-icon">✦</span>
          <strong>근거 기반 설비 관리</strong>
          <p>설비 정보를 한눈에 확인하고 필요한 근거를 살펴보세요.</p>
        </div>
        <p className="sidebar__caption">위잉위잉 · 설비 관리</p>
      </div>
    </aside>
  )
}
