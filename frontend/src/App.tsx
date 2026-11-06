import { useCallback, useEffect, useState } from "react";
import {
  currentUser,
  loginUser,
  logoutUser,
  setAccessToken,
} from "./api/client";
import AppShell from "./components/layout/AppShell";
import DashboardPage from "./views/DashboardPage";
import HomePage from "./views/HomePage";
import LoginPage from "./views/LoginPage";
import { ManualPage, ManualUploadPage } from "./views/ManualPages";
import IncidentHistoryPage from "./incident-hmi/pages/IncidentHistoryPage";
import MaintenancePage from "./views/MaintenancePage";
import ReportDraftModal from "./components/report/ReportDraftModal";
import SignupPage from "./views/SignupPage";
import ForgotPasswordPage from "./views/ForgotPasswordPage";
import MyPage from "./views/MyPage";

type SelectedIncident = { incident_id: string };
type ReportSelection = {
  incident: SelectedIncident | null;
  incidentId: string;
  reportId: string;
  version?: number;
  previewOnly?: boolean;
};
type View = { page: string; reportSelection: ReportSelection | null };
type Account = {
  name: string;
  role: string;
  employee_no: string;
  is_admin: boolean;
};

const sessionKey = "weeing-report-session";
const historyKey = "weeing-app-view";
const pages = new Set([
  "home",
  "dashboard",
  "manuals",
  "manual-upload",
  "maintenance",
  "incidents",
  "mypage",
]);

function readHistoryView(): View | null {
  if (typeof window === "undefined") return null;
  const view = window.history.state?.[historyKey];
  return view && pages.has(view.page) ? view : null;
}

function writeHistoryView(view: View, replace = false) {
  if (typeof window === "undefined") return;
  const state = { ...(window.history.state || {}), [historyKey]: view };
  const method = replace ? "replaceState" : "pushState";
  window.history[method](state, "", window.location.href);
}

function initialTheme() {
  try {
    const saved = localStorage.getItem("weeing-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* Storage may be unavailable. */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export default function App() {
  const [theme, setTheme] = useState(initialTheme);
  const [authPage, setAuthPage] = useState("login");
  const [user, setUser] = useState<Account | null>(null);
  const [checking, setChecking] = useState(() =>
    Boolean(sessionStorage.getItem(sessionKey)),
  );
  const [initialView] = useState(
    () => readHistoryView() || { page: "home", reportSelection: null },
  );
  const [reportSelection, setReportSelection] = useState(
    initialView.reportSelection || null,
  );
  const [page, setPage] = useState(initialView.page);
  const [incidentFocus, setIncidentFocus] = useState<{
    id: string;
    key: number;
  } | null>(null);
  const [maintenanceRefreshKey, setMaintenanceRefreshKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const forgetSession = useCallback(() => {
    setAccessToken("");
    sessionStorage.removeItem(sessionKey);
    setUser(null);
    setAuthPage("login");
    setPage("home");
    setReportSelection(null);
    setIncidentFocus(null);
    writeHistoryView({ page: "home", reportSelection: null }, true);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("weeing-theme", theme);
    } catch {
      /* Theme still works for this session. */
    }
  }, [theme]);

  useEffect(() => {
    if (!readHistoryView()) {
      writeHistoryView({ page, reportSelection }, true);
    }

    function restoreHistoryView() {
      const view = readHistoryView();
      setPage(view?.page || "home");
      setReportSelection(view?.reportSelection || null);
    }

    window.addEventListener("popstate", restoreHistoryView);
    return () => window.removeEventListener("popstate", restoreHistoryView);
  }, []);

  useEffect(() => {
    const token = sessionStorage.getItem(sessionKey);
    if (!token) return;
    let cancelled = false;
    setAccessToken(token);
    currentUser()
      .then((account) => {
        if (!cancelled) setUser(account);
      })
      .catch((failure) => {
        if (cancelled) return;
        if (failure.status === 401) forgetSession();
        setError(failure.message);
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [forgetSession]);

  async function login(employeeNo: string, password: string) {
    const session = await loginUser(employeeNo, password);
    sessionStorage.setItem(sessionKey, session.access_token);
    setAccessToken(session.access_token);
    setError("");
    setUser(session.user);
    setPage("home");
    setReportSelection(null);
    writeHistoryView({ page: "home", reportSelection: null }, true);
  }

  async function logout() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await logoutUser();
      forgetSession();
    } catch (failure) {
      if (
        failure instanceof Error &&
        "status" in failure &&
        failure.status === 401
      )
        forgetSession();
      setError(
        failure instanceof Error ? failure.message : "로그아웃에 실패했습니다.",
      );
    } finally {
      setBusy(false);
    }
  }

  const navigate = useCallback((nextPage: string) => {
    if (!pages.has(nextPage)) return;
    const nextView = { page: nextPage, reportSelection: null };
    writeHistoryView(nextView);
    setPage(nextPage);
    setReportSelection(null);
  }, []);

  const clearIncidentFocus = useCallback((key: number) => {
    setIncidentFocus((current) => (current?.key === key ? null : current));
  }, []);

  const openReportDraft = useCallback(
    (
      incident: SelectedIncident | null | undefined,
      reportId = "",
      row: { incidentId: string | null } | null = null,
      version?: number,
    ) => {
      const selectedIncident =
        incident || (row?.incidentId ? { incident_id: row.incidentId } : null);
      if (!selectedIncident && !reportId) {
        setError("사건 정보를 찾을 수 없어 보고서를 열 수 없습니다.");
        return;
      }

      const selection = {
        incident: selectedIncident,
        incidentId: selectedIncident?.incident_id || "",
        reportId,
        version,
      };

      const origin = page === "incidents" ? "incidents" : "maintenance";
      if (page !== origin) {
        writeHistoryView({ page: origin, reportSelection: null });
      }
      const nextView = { page: origin, reportSelection: selection };
      writeHistoryView(nextView);
      setPage(origin);
      setReportSelection(selection);
      setError("");
    },
    [page],
  );

  const closeReportDraft = useCallback(() => {
    if (readHistoryView()?.reportSelection) {
      window.history.back();
      return;
    }
    const origin = page === "incidents" ? "incidents" : "maintenance";
    const nextView = { page: origin, reportSelection: null };
    writeHistoryView(nextView, true);
    setPage(origin);
    setReportSelection(null);
  }, [page]);

  function handleReportSaved() {
    setMaintenanceRefreshKey((key) => key + 1);
    window.dispatchEvent(new Event("weeing-incidents-changed"));
  }

  if (checking)
    return (
      <main className="login-page">
        <p role="status">로그인 상태를 확인하고 있습니다.</p>
      </main>
    );
  if (!user)
    return authPage === "signup" ? (
      <SignupPage onLogin={() => setAuthPage("login")} />
    ) : authPage === "forgot" ? (
      <ForgotPasswordPage onLogin={() => setAuthPage("login")} />
    ) : (
      <LoginPage
        onLogin={login}
        onSignup={() => setAuthPage("signup")}
        onForgotPassword={() => setAuthPage("forgot")}
        error={error}
      />
    );

  return (
    <AppShell
      onSessionExpired={forgetSession}
      user={user}
      onLogout={logout}
      busy={busy}
      page={page}
      onNavigate={navigate}
      onIncidentSelect={(incident: SelectedIncident) => {
        navigate("incidents");
        setIncidentFocus({ id: incident.incident_id, key: Date.now() });
      }}
      theme={theme}
      onToggleTheme={() =>
        setTheme((current) => (current === "light" ? "dark" : "light"))
      }
    >
      {error && (
        <p className="workspace-error" role="alert">
          {error}
        </p>
      )}
      {page === "home" && (
        <HomePage
          user={user}
          onNavigate={navigate}
          onSessionExpired={forgetSession}
          onOpenReport={(id) => openReportDraft(null, id)}
        />
      )}
      <div hidden={page !== "dashboard"}>
        <DashboardPage onSessionExpired={forgetSession} onNavigate={navigate} />
      </div>
      {page === "mypage" && (
        <MyPage
          user={user}
          onNavigate={navigate}
          onSessionExpired={forgetSession}
          onOpen={(id) => openReportDraft(null, id)}
        />
      )}
      {page === "manuals" && (
        <ManualPage
          user={user}
          onNavigate={navigate}
          onSessionExpired={forgetSession}
          onBusyChange={setBusy}
        />
      )}
      {page === "manual-upload" && user?.role === "관제 담당자" && (
        <ManualUploadPage
          onNavigate={navigate}
          onSessionExpired={forgetSession}
          onBusyChange={setBusy}
        />
      )}
      {page === "maintenance" && (
        <MaintenancePage
          user={user}
          onSessionExpired={forgetSession}
          refreshKey={maintenanceRefreshKey}
          onOpen={(reportId, _incidentId, row) =>
            openReportDraft(row?.incident, reportId, row)
          }
        />
      )}
      {page === "incidents" && (
        <IncidentHistoryPage
          user={user}
          busy={busy}
          onBusyChange={setBusy}
          focus={incidentFocus}
          onFocusHandled={clearIncidentFocus}
          onSessionExpired={forgetSession}
          onOpenDraft={(incidentId) =>
            openReportDraft({ incident_id: incidentId })
          }
          onOpenReport={(reportId, incidentId, version) =>
            openReportDraft(
              incidentId ? { incident_id: incidentId } : null,
              reportId,
              null,
              version,
            )
          }
        />
      )}
      {reportSelection && (
        <ReportDraftModal
          key={`${reportSelection.incidentId}:${reportSelection.reportId || "new"}`}
          incident={reportSelection.incident}
          reportId={reportSelection.reportId}
          version={reportSelection.version}
          previewOnly={reportSelection.previewOnly}
          user={user}
          onClose={closeReportDraft}
          onSaved={handleReportSaved}
          onSessionExpired={forgetSession}
        />
      )}
    </AppShell>
  );
}
