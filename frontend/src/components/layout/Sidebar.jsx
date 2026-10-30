const navigation = [
  { icon: 'f1f1d', label: '설비 모니터링', id: 'monitoring', pending: true },
  { icon: '5dd0d', label: '대시보드', id: 'dashboard' },
  { icon: '3a495', activeIcon: '0dea7', label: '문서 내역', id: 'manuals' },
  { icon: 'd141d', activeIcon: '4741e', label: '정비 이력', id: 'maintenance' },
]
export default function Sidebar({ page, onNavigate, busy }) {
  const current =
    page === 'manual-upload'
      ? 'manuals'
      : page === 'report-write'
        ? 'maintenance'
        : page
  return (
    <aside className="sidebar">
      <div className="sidebar__label">WORKSPACE</div>
      <nav aria-label="주 메뉴">
        {navigation.map(({ icon, activeIcon, label, id, pending }) => (
          <button
            key={id}
            type="button"
            className={`nav-item ${current === id ? 'nav-item--active' : ''}`}
            aria-current={current === id ? 'page' : undefined}
            disabled={busy || pending}
            title={pending ? '설비 모니터링 준비 중' : label}
            onClick={() => onNavigate(id)}
          >
            <img
              src={`/assets/ICONS/${current === id && activeIcon ? activeIcon : icon}.svg`}
              alt=""
            />
            {label}
          </button>
        ))}
      </nav>
      <div className="sidebar__bottom">
        <p className="sidebar__caption">위잉위잉 · 설비 관리</p>
      </div>
    </aside>
  )
}
