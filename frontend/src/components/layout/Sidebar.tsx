import { useEffect, useState } from "react";

type NavigationItem = {
  icon: string;
  activeIcon?: string;
  label: string;
  id: string;
  pending?: boolean;
};

const navigation: NavigationItem[] = [
  // { icon: 'f1f1d', label: '설비 모니터링', id: 'monitoring', pending: true },
  { icon: "5dd0d", label: "대시보드", id: "home" },
  { icon: "f1f1d", label: "이상현황", id: "incidents" },
  { icon: "3a495", activeIcon: "0dea7", label: "문서내역", id: "manuals" },
  { icon: "d141d", activeIcon: "4741e", label: "정비이력", id: "maintenance" },
  {
    icon: "mypage",
    activeIcon: "mypage-active",
    label: "마이페이지",
    id: "mypage",
  },
];
export default function Sidebar({
  page,
  onNavigate,
  busy,
  collapsed = false,
  onToggleCollapsed,
}: {
  page: string;
  onNavigate: (page: string) => void;
  busy: boolean;
  collapsed?: boolean;
  onToggleCollapsed: () => void;
}) {
  // 설비 상세 대시보드(dashboard)도 메인 대시보드 메뉴 아래에 있는 화면이다.
  const current =
    page === "manual-upload"
      ? "manuals"
      : page === "report-write"
        ? "maintenance"
        : page === "dashboard"
          ? "home"
          : page;
  // 좁은 화면에서는 메뉴를 드롭다운으로 접어 둔다.
  const [menuOpen, setMenuOpen] = useState(false);
  const currentItem = navigation.find((item) => item.id === current);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menuOpen]);

  return (
    <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`}>
      <button
        type="button"
        className="sidebar__toggle"
        aria-label={collapsed ? "사이드 메뉴 펼치기" : "사이드 메뉴 접기"}
        aria-expanded={!collapsed}
        title={collapsed ? "사이드 메뉴 펼치기" : "사이드 메뉴 접기"}
        onClick={onToggleCollapsed}
      >
        <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path
            d="M8 1.5 3.5 6 8 10.5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <button
        type="button"
        className="sidebar__mobile-toggle"
        aria-expanded={menuOpen}
        aria-controls="sidebar-nav"
        onClick={() => setMenuOpen((open) => !open)}
      >
        {currentItem && (
          <img
            src={`/assets/ICONS/${currentItem.activeIcon ?? currentItem.icon}.svg`}
            alt=""
          />
        )}
        <span>{currentItem?.label ?? "메뉴"}</span>
        <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path
            d="M2 4.2 6 8l4-3.8"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <nav
        id="sidebar-nav"
        aria-label="주 메뉴"
        className={menuOpen ? "is-open" : undefined}
      >
        {navigation.map(({ icon, activeIcon, label, id, pending }) => (
          <button
            key={id}
            type="button"
            className={`nav-item ${current === id ? "nav-item--active" : ""}`}
            aria-current={current === id ? "page" : undefined}
            aria-label={label}
            disabled={busy || pending}
            data-tooltip={collapsed ? label : undefined}
            title={
              collapsed ? undefined : pending ? "설비 모니터링 준비 중" : label
            }
            onClick={() => {
              setMenuOpen(false);
              onNavigate(id);
            }}
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
        <p className="sidebar__caption">
          Copyright © 위잉위잉.
          <br />
          All rights reserved.
        </p>
      </div>
    </aside>
  );
}
