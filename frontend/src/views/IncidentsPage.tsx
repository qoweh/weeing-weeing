import { useEffect, useState } from "react";
import {
  listIncidents,
  listIncidentOverview,
  type Incident,
  type ReportSummary,
} from "../api/client";
import Button from "../components/ui/Button";
import PageTitle from "../components/ui/PageTitle";
import { LibraryTable } from "../components/ui/library";
const labels: Record<string, string> = {
  DRAFT: "임시 저장",
  SUBMITTED: "검토 중",
  REVIEWED: "검토 승인",
  APPROVED: "작성 완료",
  REJECTED: "반려",
};
const activeStatuses = ["OPEN", "ACKNOWLEDGED"];
const issueLimit = 3;
const refreshIntervalMs = 2000;
// 아직 접수되지 않은 사건(OPEN)을 먼저, 같은 상태에서는 최근 발생한 사건을 먼저 둔다.
const urgency = (incident: Incident) => {
  const index = activeStatuses.indexOf(incident.status);
  return index < 0 ? activeStatuses.length : index;
};
const byUrgency = (a: Incident, b: Incident) =>
  urgency(a) - urgency(b) ||
  String(b.first_detected_at).localeCompare(String(a.first_detected_at));

function toRow(incident: Incident, reports: ReportSummary[]) {
  const report = reports.find((r) => r.incident_id === incident.incident_id);
  return {
    id: report?.report_id || incident.incident_id,
    reportId: report?.report_id,
    incidentId: incident.incident_id,
    name: report?.report_id || "보고서 작성",
    issue: incident.codes.join(", "),
    asset: incident.asset_id,
    date: incident.first_detected_at,
    author: report?.author_name || "—",
    status: report ? labels[report.report_status] : "작성 필요",
    tone: "warning",
    incident,
  };
}

export default function IncidentsPage({
  onOpen,
  onSessionExpired,
  refreshKey = 0,
}: {
  onOpen: (
    reportId: string | undefined,
    incidentId: string,
    row: ReturnType<typeof toRow>,
  ) => void;
  onSessionExpired: () => void;
  refreshKey?: number;
}) {
  const [issues, setIssues] = useState<ReturnType<typeof toRow>[]>([]),
    [history, setHistory] = useState<ReturnType<typeof toRow>[]>([]);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0);
  useEffect(() => {
    const changed = () => setReload((n) => n + 1);
    window.addEventListener("weeing-incidents-changed", changed);
    return () =>
      window.removeEventListener("weeing-incidents-changed", changed);
  }, []);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      try {
        const overview = await listIncidentOverview();
        if (!active) return;
        const row = (item: (typeof overview)[number]) =>
          toRow(
            item.incident,
            item.report_id
              ? [
                  {
                    report_id: item.report_id,
                    incident_id: item.incident.incident_id,
                    report_status: item.report_status || "",
                    author_name: "",
                    asset_id: item.incident.asset_id,
                    updated_at: "",
                  },
                ]
              : [],
          );
        setIssues(
          overview
            .filter((item) => !item.has_approved_report)
            .sort((a, b) => byUrgency(a.incident, b.incident))
            .map(row),
        );
        setHistory(
          overview.filter((item) => item.has_approved_report).map(row),
        );
        setError("");
      } catch (e) {
        if (active) {
          setError(
            e instanceof Error ? e.message : "목록 조회에 실패했습니다.",
          );
          if (e && typeof e === "object" && "status" in e && e.status === 401)
            onSessionExpired();
          else {
            try {
              const incidents = await listIncidents();
              if (active)
                setIssues(
                  incidents
                    .filter((i) => i.severity === "Error")
                    .sort(byUrgency)
                    .map((i) => toRow(i, [])),
                );
            } catch {
              /* Preserve the last known list when both requests fail. */
            }
          }
        }
      } finally {
        if (active) {
          setLoading(false);
          timer = setTimeout(refresh, refreshIntervalMs);
        }
      }
    }
    refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [reload, refreshKey, onSessionExpired]);
  return (
    <div className="library-page" aria-label="이상 현황">
      <PageTitle>이상현황</PageTitle>
      {loading ? (
        <p role="status">이상 현황을 불러오는 중입니다.</p>
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
            compact
            title="오류 이슈"
            emptyTitle="진행 중인 오류 이슈가 없습니다"
            emptyHint="새로운 이상이 감지되면 이곳에 표시됩니다."
            rows={issues.slice(0, issueLimit)}
            totalCount={issues.length}
            initialSort={{ key: "number", direction: 1 }}
            hint={`보고서 승인 전 사건 중 우선순위 상위 ${issueLimit}건을 표시합니다 (최근 200건)`}
            onOpen={(r: ReturnType<typeof toRow>) =>
              onOpen(r.reportId, r.incidentId, r)
            }
          />
          <LibraryTable
            report
            compact
            title="오류 히스토리"
            emptyTitle={undefined}
            emptyHint={undefined}
            totalCount={undefined}
            rows={history}
            alwaysPaginate
            onOpen={(r: ReturnType<typeof toRow>) =>
              onOpen(r.reportId, r.incidentId, r)
            }
          />
        </>
      )}
    </div>
  );
}
