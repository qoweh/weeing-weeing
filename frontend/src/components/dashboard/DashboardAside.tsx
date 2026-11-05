import { useEffect, useState } from "react";
import {
  getMlPrediction,
  listDocuments,
  listIncidentOverview,
  listReports,
  type IncidentOverview,
  type MlSnapshot,
  type ReportSummary,
} from "../../api/client";

type DocumentItem = {
  doc_id: string;
  doc_version: string;
  title?: string;
  doc_type?: string;
};

const activeStatuses = ["OPEN", "ACKNOWLEDGED"];
const statusLabel: Record<string, string> = {
  OPEN: "확인 대기",
  ACKNOWLEDGED: "확인함",
};
const severityLabel: Record<string, string> = {
  Error: "경고",
  Warning: "주의",
};
const reportLabel: Record<string, string> = {
  DRAFT: "임시 저장",
  SUBMITTED: "검토 중",
  REVIEWED: "검토 승인",
  APPROVED: "작성 완료",
  REJECTED: "반려",
};
const reportTone: Record<string, string> = {
  APPROVED: "success",
  REJECTED: "danger",
};
const listLimit = 3;
const predictionRefreshMs = 2000;
const orangeFrom = 0.6;
const redFrom = 0.8;

function probabilityTone(value: number) {
  if (value >= redFrom) return "danger";
  if (value >= orangeFrom) return "orange";
  return "normal";
}

const percent = (value: number) => `${Math.round(value * 1000) / 10}%`;

type PredictionRow = { code: string; probability: number };

// 확률이 높은 순 TOP3. fault_top3가 없으면 probabilities에서 NO_ERROR를 뺀 값으로 대신한다.
function topPredictions(prediction: MlSnapshot["prediction"]): PredictionRow[] {
  const rows: PredictionRow[] = prediction.fault_top3
    ? prediction.fault_top3.map((item) => ({
        code: item.code,
        probability: item.confidence,
      }))
    : Object.entries(prediction.probabilities ?? {})
        .filter(([code]) => code !== "NO_ERROR")
        .map(([code, probability]) => ({ code, probability }));
  return rows
    .filter((row) => Number.isFinite(row.probability))
    .sort((a, b) => b.probability - a.probability)
    .slice(0, 3);
}

function predictionNotice(snapshot: MlSnapshot | null, lost: boolean) {
  if (lost || !snapshot) return "연결이 끊겼습니다.";
  if (!snapshot.enabled) return "예측 기능이 꺼져 있습니다.";
  if (!snapshot.producer_connected || snapshot.stale)
    return "연결이 끊겼습니다.";
  if (snapshot.prediction.status === "not_ready")
    return "예측을 준비하고 있습니다.";
  if (!snapshot.prediction_usable) return "지금은 예측을 표시할 수 없습니다.";
  return "";
}
const refreshMs = 10_000;

function isUnauthorized(error: unknown) {
  return (
    !!error &&
    typeof error === "object" &&
    "status" in error &&
    error.status === 401
  );
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function DashboardAside({
  onNavigate,
  onSessionExpired,
}: {
  onNavigate?: (page: string) => void;
  onSessionExpired?: () => void;
}) {
  const [incidents, setIncidents] = useState<IncidentOverview[] | null>(null);
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[] | null>(null);
  const [mlSnapshot, setMlSnapshot] = useState<MlSnapshot | null>(null);
  const [mlLost, setMlLost] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const value = await getMlPrediction();
        if (active) {
          setMlSnapshot(value);
          setMlLost(false);
        }
      } catch (error) {
        if (active) {
          if (isUnauthorized(error)) onSessionExpired?.();
          setMlLost(true);
        }
      }
      if (active) timer = setTimeout(poll, predictionRefreshMs);
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [onSessionExpired]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // 각 목록은 독립적으로 불러와 한 곳이 실패해도 나머지는 유지한다.
    async function load<T>(fetcher: () => Promise<T>, apply: (v: T) => void) {
      try {
        const value = await fetcher();
        if (active) apply(value);
      } catch (error) {
        if (active && isUnauthorized(error)) onSessionExpired?.();
      }
    }
    async function refresh() {
      await Promise.all([
        load(listIncidentOverview, setIncidents),
        load(() => listReports("all"), setReports),
        load(
          () => listDocuments() as Promise<DocumentItem[]>,
          (v) => setDocuments(Array.isArray(v) ? v : []),
        ),
      ]);
      if (active) timer = setTimeout(refresh, refreshMs);
    }
    refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [onSessionExpired]);

  const activeIncidents = (incidents ?? [])
    .filter(({ incident }) => activeStatuses.includes(incident.status))
    .sort((a, b) =>
      String(b.incident.first_detected_at).localeCompare(
        String(a.incident.first_detected_at),
      ),
    );
  const recentReports = [...(reports ?? [])]
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
    .slice(0, listLimit);
  const notice = predictionNotice(mlSnapshot, mlLost);
  const predictionData = notice ? null : (mlSnapshot?.prediction ?? null);
  const predictionRows = predictionData ? topPredictions(predictionData) : [];
  const errorProbability = predictionData?.error_probability;
  const recentDocuments = (documents ?? []).slice(0, listLimit);

  return (
    <aside className="dashboard-aside" aria-label="설비 현황 요약">
      <section className="dashboard-panel" aria-labelledby="aside-predictions">
        <h2 id="aside-predictions">예측 이상 현상 내역</h2>
        {notice ? (
          <p
            className="dashboard-panel__notice"
            data-lost={notice === "연결이 끊겼습니다."}
            role="status"
          >
            {notice}
          </p>
        ) : (
          <>
            {typeof errorProbability === "number" && (
              <p
                className="dashboard-prediction__summary"
                data-tone={probabilityTone(errorProbability)}
              >
                향후 60초 에러 확률 <strong>{percent(errorProbability)}</strong>
              </p>
            )}
            <ul>
              {predictionRows.map((item) => (
                <li
                  key={item.code}
                  className="dashboard-prediction"
                  data-tone={probabilityTone(item.probability)}
                >
                  <span className="dashboard-panel__row">
                    <strong>{item.code}</strong>
                    <span className="dashboard-prediction__percent">
                      {percent(item.probability)}
                    </span>
                  </span>
                  <span
                    className="dashboard-prediction__bar"
                    role="img"
                    aria-label={`${item.code} 예측 확률 ${percent(item.probability)}`}
                  >
                    <span
                      style={{
                        width: `${Math.min(100, item.probability * 100)}%`,
                      }}
                    />
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="dashboard-panel" aria-labelledby="aside-reports">
        <h2 id="aside-reports">최근 정비 이력</h2>
        {reports === null ? (
          <p className="dashboard-panel__empty">불러오는 중입니다.</p>
        ) : recentReports.length === 0 ? (
          <p className="dashboard-panel__empty">정비 이력이 없습니다.</p>
        ) : (
          <ul>
            {recentReports.map((report) => (
              <li key={report.report_id} className="dashboard-panel__line">
                <button
                  type="button"
                  onClick={() => onNavigate?.("maintenance")}
                >
                  {report.report_id}
                </button>
                <span
                  className="dashboard-badge"
                  data-tone={reportTone[report.report_status] ?? "info"}
                >
                  {reportLabel[report.report_status] ?? report.report_status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="dashboard-panel" aria-labelledby="aside-documents">
        <h2 id="aside-documents">관련 문서</h2>
        {documents === null ? (
          <p className="dashboard-panel__empty">불러오는 중입니다.</p>
        ) : recentDocuments.length === 0 ? (
          <p className="dashboard-panel__empty">등록된 문서가 없습니다.</p>
        ) : (
          <ul>
            {recentDocuments.map((doc) => (
              <li
                key={`${doc.doc_id}:${doc.doc_version}`}
                className="dashboard-panel__line"
              >
                <button type="button" onClick={() => onNavigate?.("manuals")}>
                  {doc.title || doc.doc_id}
                </button>
                <span className="dashboard-panel__meta">
                  v{doc.doc_version}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="dashboard-panel" aria-labelledby="aside-incidents">
        <h2 id="aside-incidents">진행 중인 이상</h2>
        <p className="dashboard-panel__hint">클릭하면 사건 상세로 이동합니다</p>
        {incidents === null ? (
          <p className="dashboard-panel__empty">불러오는 중입니다.</p>
        ) : activeIncidents.length === 0 ? (
          <p className="dashboard-panel__empty">진행 중인 이상이 없습니다.</p>
        ) : (
          <ul>
            {activeIncidents.slice(0, listLimit).map(({ incident }) => (
              <li key={incident.incident_id}>
                <button
                  type="button"
                  className="dashboard-panel__incident"
                  onClick={() => onNavigate?.("incidents")}
                >
                  <span className="dashboard-panel__row">
                    <strong>{incident.incident_id}</strong>
                    <span
                      className="dashboard-badge"
                      data-tone={
                        incident.severity === "Error" ? "danger" : "warning"
                      }
                    >
                      {severityLabel[incident.severity] ?? incident.severity}
                    </span>
                  </span>
                  <span>{incident.codes.join(", ") || incident.asset_id}</span>
                  <small>
                    발생 {formatTime(incident.first_detected_at)} ·{" "}
                    {statusLabel[incident.status] ?? incident.status}
                  </small>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  );
}
