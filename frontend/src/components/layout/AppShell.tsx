import { useEffect, useState, type ReactNode } from "react";
import ChatWidget from "../chat/ChatWidget.jsx";
import { listAllReports, type Incident } from "../../api/client";
import Header from "./Header";
import Sidebar from "./Sidebar";
import "./layout.scss";
import {
  readSettings,
  saveSettings,
  SettingsContext,
  SettingsUpdateContext,
  type Settings,
} from "./settings";

export default function AppShell({
  theme,
  onToggleTheme,
  user,
  onLogout,
  busy,
  page,
  onNavigate,
  onIncidentSelect,
  onSessionExpired,
  children,
}: {
  theme: string;
  onToggleTheme: () => void;
  user: { name: string; role: string; employee_no: string };
  onLogout: () => void;
  busy: boolean;
  page: string;
  onNavigate: (page: string) => void;
  onIncidentSelect: (incident: Incident) => void;
  onSessionExpired: () => void;
  children: ReactNode;
}) {
  const [settings, setSettings] = useState(readSettings);
  const [maintenanceAttention, setMaintenanceAttention] = useState(false);
  useEffect(() => {
    let active = true;
    let sequence = 0;
    async function refresh() {
      const current = ++sequence;
      try {
        const canReview = ["보전 팀장", "관제 담당자"].includes(user.role);
        const canWrite = ["현장 점검자", "보전 팀장"].includes(user.role);
        const [mine, review] = await Promise.all([
          canWrite ? listAllReports("mine") : Promise.resolve([]),
          canReview ? listAllReports("review") : Promise.resolve([]),
        ]);
        if (active && current === sequence)
          setMaintenanceAttention(
            mine.some((report) => report.report_status === "REJECTED") ||
              review.length > 0,
          );
      } catch {
        // 일시적인 조회 실패 시 마지막으로 확인한 상태를 유지한다.
      }
    }
    setMaintenanceAttention(false);
    void refresh();
    const timer = window.setInterval(refresh, 30000);
    window.addEventListener("weeing-reports-changed", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("weeing-reports-changed", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, [user.employee_no, user.role]);
  function changeSettings(next: Settings) {
    setSettings(next);
    saveSettings(next);
  }
  const updateSettings = (patch: Partial<Settings>) =>
    changeSettings({ ...settings, ...patch });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem("weeing-sidebar") === "collapsed";
    } catch {
      return false;
    }
  });
  function changeSidebarCollapsed(next: boolean) {
    setSidebarCollapsed(next);
    try {
      localStorage.setItem("weeing-sidebar", next ? "collapsed" : "expanded");
    } catch {
      /* Storage may be unavailable. */
    }
  }
  // 기본 화면 비율: 화면 폭이 1800px보다 좁은 노트북은 90%, 넓은 모니터는 100%.
  // 사용자가 직접 바꾼 값은 이 브라우저에 저장해 다음에도 유지한다.
  const [defaultScreenZoom] = useState(() =>
    window.innerWidth < 1800 ? 90 : 100,
  );
  const [screenZoom, setScreenZoom] = useState(() => {
    try {
      const saved = Number(localStorage.getItem("weeing-zoom"));
      if ([80, 90, 100, 110, 120].includes(saved)) return saved;
    } catch {
      /* Storage may be unavailable. */
    }
    return defaultScreenZoom;
  });
  function changeScreenZoom(next: number | ((value: number) => number)) {
    const value = typeof next === "function" ? next(screenZoom) : next;
    setScreenZoom(value);
    try {
      localStorage.setItem("weeing-zoom", String(value));
    } catch {
      /* Storage may be unavailable. */
    }
  }
  function resetScreenZoom() {
    setScreenZoom(defaultScreenZoom);
    try {
      localStorage.removeItem("weeing-zoom");
    } catch {
      /* Storage may be unavailable. */
    }
  }

  useEffect(() => {
    document.documentElement.style.zoom = `${screenZoom}%`;
    // zoom은 vh까지 같이 배율을 곱하므로, 셸 높이가 화면에 맞도록 배율을 CSS 변수로 넘긴다.
    document.documentElement.style.setProperty(
      "--screen-zoom",
      String(screenZoom / 100),
    );
    return () => {
      document.documentElement.style.zoom = "";
      document.documentElement.style.removeProperty("--screen-zoom");
    };
  }, [screenZoom]);

  useEffect(() => {
    function preventZoomShortcut(event: KeyboardEvent) {
      if (
        (event.ctrlKey || event.metaKey) &&
        (["+", "-", "=", "_"].includes(event.key) ||
          ["NumpadAdd", "NumpadSubtract"].includes(event.code))
      ) {
        event.preventDefault();
      }
    }
    function preventZoomWheel(event: WheelEvent) {
      if (event.ctrlKey || event.metaKey) event.preventDefault();
    }
    window.addEventListener("keydown", preventZoomShortcut, true);
    window.addEventListener("wheel", preventZoomWheel, {
      passive: false,
      capture: true,
    });
    return () => {
      window.removeEventListener("keydown", preventZoomShortcut, true);
      window.removeEventListener("wheel", preventZoomWheel, true);
    };
  }, []);

  return (
    <div className={`shell ${sidebarCollapsed ? "shell--collapsed" : ""}`}>
      <Header
        user={user}
        onLogout={onLogout}
        busy={busy}
        theme={theme}
        onToggleTheme={onToggleTheme}
        screenZoom={screenZoom}
        onChangeScreenZoom={changeScreenZoom}
        defaultScreenZoom={defaultScreenZoom}
        onResetScreenZoom={resetScreenZoom}
        sidebarCollapsed={sidebarCollapsed}
        onChangeSidebarCollapsed={changeSidebarCollapsed}
        onIncidentSelect={onIncidentSelect}
        onNavigateDashboard={() => onNavigate("home")}
        onSessionExpired={onSessionExpired}
        settings={settings}
        onChangeSettings={changeSettings}
      />
      <Sidebar
        maintenanceAttention={maintenanceAttention}
        page={page}
        onNavigate={onNavigate}
        busy={busy}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => changeSidebarCollapsed(!sidebarCollapsed)}
      />
      <main className="shell__content" id="main-content">
        <SettingsContext.Provider value={settings}>
          <SettingsUpdateContext.Provider value={updateSettings}>
            {children}
          </SettingsUpdateContext.Provider>
        </SettingsContext.Provider>
      </main>
      <ChatWidget
        screenZoom={screenZoom}
        displayMode={settings.chatDisplay}
        onSessionExpired={onSessionExpired}
      />
    </div>
  );
}
