type NavigationItem = {
  icon: string
  activeIcon?: string
  label: string
  id: string
  pending?: boolean
}

const navigation: NavigationItem[] = [
  // { icon: 'f1f1d', label: '설비 모니터링', id: 'monitoring', pending: true },
  { icon: '5dd0d', label: '대시보드', id: 'dashboard' },
  { icon: 'f1f1d', label: '이상현황', id: 'incidents' },
  { icon: '3a495', activeIcon: '0dea7', label: '문서내역', id: 'manuals' },
  { icon: 'd141d', activeIcon: '4741e', label: '정비이력', id: 'maintenance' },
  {
    icon: 'mypage',
    activeIcon: 'mypage-active',
    label: '마이페이지',
    id: 'mypage',
  },
]
export default function Sidebar({
  page,
  onNavigate,
  busy,
  collapsed = false,
  onToggleCollapsed,
}: {
  page: string
  onNavigate: (page: string) => void
  busy: boolean
  collapsed?: boolean
  onToggleCollapsed: () => void
}) {
  const current =
    page === 'manual-upload'
      ? 'manuals'
      : page === 'report-write'
        ? 'maintenance'
        : page
  return (
    <aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
      <div className="sidebar__top">
        <div className="sidebar__label">WORKSPACE</div>
        <button
          type="button"
          className="sidebar__toggle"
          aria-label={collapsed ? '사이드 메뉴 펼치기' : '사이드 메뉴 접기'}
          aria-expanded={!collapsed}
          title={collapsed ? '사이드 메뉴 펼치기' : '사이드 메뉴 접기'}
          onClick={onToggleCollapsed}
        >
          <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path
              d={collapsed ? 'M4 1.5 8.5 6 4 10.5' : 'M8 1.5 3.5 6 8 10.5'}
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
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
            <span className="nav-item__label">{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar__bottom">
        <p className="sidebar__caption">위잉위잉 · 설비 관리</p>
      </div>
    </aside>
  )
}
