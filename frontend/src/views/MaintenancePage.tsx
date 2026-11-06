import { useEffect, useState } from "react";
import {
  listAllReports,
  listAllReviewHistory,
  listAllIncidents,
  type Incident,
} from "../api/client";
import Button from "../components/ui/Button";
import PageTitle from "../components/ui/PageTitle";
import { incidentCodesText } from "../components/ui/incidentCodes";
import { Filters, filterRows, LibraryTable } from "../components/ui/library";
type Row = {
  id: string;
  reportId: string;
  incidentId: string | null;
  name: string;
  issue: string;
  issueCodes?: string[];
  asset: string;
  date: string;
  author: string;
  incident?: Incident;
  status: string;
  tone: string;
};

const labels: Record<string, string> = {
  DRAFT: "임시 저장",
  SUBMITTED: "검토 중",
  REVIEWED: "검토 승인",
  APPROVED: "작성 완료",
  REJECTED: "반려",
};
export default function MaintenancePage({
  user,
  onOpen,
  onSessionExpired,
  refreshKey = 0,
}: {
  user: { role: string };
  onOpen: (reportId: string, incidentId: string | null, row: Row) => void;
  onSessionExpired: () => void;
  refreshKey?: number;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [query, setQuery] = useState(""),
    [filters, setFilters] = useState({ period: "", docType: "" });
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0);
  const [scope, setScope] = useState<"all" | "mine" | "review" | "history">(
    "all",
  );
  const [reviewCount, setReviewCount] = useState<number | null>(null);
  const [rejectedCount, setRejectedCount] = useState<number | null>(null);
  useEffect(() => {
    let active = true;
    let sequence = 0;
    async function refreshCount() {
      const current = ++sequence;
      try {
        const reports = await listAllReports("mine");
        if (active && current === sequence)
          setRejectedCount(
            reports.filter((report) => report.report_status === "REJECTED")
              .length,
          );
      } catch (error) {
        if (active && current === sequence) setRejectedCount(null);
        if (active && (error as { status?: number }).status === 401)
          onSessionExpired();
      }
    }
    void refreshCount();
    const timer = window.setInterval(refreshCount, 30000);
    window.addEventListener("focus", refreshCount);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refreshCount);
    };
  }, [user.role, refreshKey, reload, onSessionExpired]);
  useEffect(() => {
    let active = true;
    let sequence = 0;
    if (!["보전 팀장", "관제 담당자"].includes(user.role)) {
      setReviewCount(null);
      return;
    }
    async function refreshCount() {
      const current = ++sequence;
      try {
        const reports = await listAllReports("review");
        if (active && current === sequence) setReviewCount(reports.length);
      } catch (error) {
        if (active && current === sequence) setReviewCount(null);
        if (active && (error as { status?: number }).status === 401)
          onSessionExpired();
      }
    }
    void refreshCount();
    const timer = window.setInterval(refreshCount, 30000);
    window.addEventListener("focus", refreshCount);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refreshCount);
    };
  }, [user.role, refreshKey, reload, onSessionExpired]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    Promise.all([
      scope === "history"
        ? listAllReviewHistory().then((items) =>
            items.map((item) => item.report),
          )
        : listAllReports(scope === "all" ? "approved" : scope),
      listAllIncidents(),
    ])
      .then(([reports, incidents]) => {
        if (!active) return;
        const mapped = reports.map((r) => {
          const incident = incidents.find(
            (i) => i.incident_id === r.incident_id,
          );
          return {
            id: r.report_id,
            reportId: r.report_id,
            incidentId: r.incident_id,
            name: r.report_id,
            issue:
              incidentCodesText(incident?.codes) ||
              r.incident_id ||
              "사건 미연결",
            issueCodes: incident?.codes,
            asset: r.asset_id,
            date: incident?.first_detected_at || r.updated_at,
            author: r.author_name,
            incident,
            status: labels[r.report_status] || r.report_status,
            tone:
              r.report_status === "APPROVED"
                ? "success"
                : r.report_status === "REJECTED"
                  ? "danger"
                  : ["SUBMITTED", "REVIEWED"].includes(r.report_status)
                    ? "warning"
                    : "neutral",
          };
        });
        setRows(mapped);
      })
      .catch((e) => {
        if (active) {
          setError(e.message);
          if (e.status === 401) onSessionExpired();
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [scope, reload, refreshKey, onSessionExpired]);
  return (
    <div className="library-page" aria-label="정비 이력 · 보고서">
      <div className="maintenance-page__heading">
        <PageTitle>정비이력</PageTitle>
      </div>
      <div
        className="library-report-scopes"
        role="group"
        aria-label="보고서 목록 선택"
      >
        <Button aria-pressed={scope === "all"} onClick={() => setScope("all")}>
          전체 보고서
        </Button>
        {user.role !== "관제 담당자" && (
          <Button
            aria-pressed={scope === "mine"}
            onClick={() => setScope("mine")}
          >
            내 보고서{" "}
            {rejectedCount !== null && rejectedCount > 0 && (
              <span
                className="library-review-count"
                aria-label={`반려된 보고서 ${rejectedCount}건`}
              >
                {rejectedCount}
              </span>
            )}
          </Button>
        )}
        {["보전 팀장", "관제 담당자"].includes(user.role) && (
          <Button
            aria-pressed={scope === "history"}
            onClick={() => setScope("history")}
          >
            내 결재 이력
          </Button>
        )}
        {["보전 팀장", "관제 담당자"].includes(user.role) && (
          <Button
            aria-pressed={scope === "review"}
            onClick={() => setScope("review")}
          >
            결재 대기{" "}
            {reviewCount !== null && reviewCount > 0 && (
              <span
                className="library-review-count"
                aria-label={`결재 대기 ${reviewCount}건`}
              >
                {reviewCount}
              </span>
            )}
          </Button>
        )}
      </div>
      <Filters
        report
        children={undefined}
        query={query}
        setQuery={setQuery}
        filters={filters}
        setFilters={setFilters}
        onRefresh={() => setReload((n) => n + 1)}
        loading={loading}
      />
      {loading ? (
        <p role="status">정비 이력을 불러오는 중입니다.</p>
      ) : (
        <>
          {error && (
            <p className="workspace-error" role="alert">
              실제 목록을 불러오지 못했습니다: {error}{" "}
              <Button onClick={() => setReload((n) => n + 1)}>다시 시도</Button>
            </p>
          )}
          <LibraryTable
            report
            emptyTitle={undefined}
            emptyHint={undefined}
            totalCount={undefined}
            title={
              {
                all: "정비 이력",
                mine: "내 보고서",
                review: "결재 대기",
                history: "내 결재 이력",
              }[scope]
            }
            rows={filterRows(rows, query, filters)}
            onOpen={(r: Row) => onOpen(r.reportId || r.id, r.incidentId, r)}
          />
        </>
      )}
    </div>
  );
}
