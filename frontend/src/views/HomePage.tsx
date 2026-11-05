import { useState } from "react";
import {
  getMlPrediction,
  listIncidentOverview,
  listReports,
} from "../api/client";
import PageTitle from "../components/ui/PageTitle";
import ApprovalCard, {
  type ApprovalTab,
} from "../components/home/ApprovalCard";
import EquipmentListCard from "../components/home/EquipmentListCard";
import PredictionCard, {
  predictionView,
} from "../components/home/PredictionCard";
import {
  activeIncidents,
  buildEquipmentRows,
} from "../components/home/homeData";
import {
  percent,
  probabilityTone,
} from "../components/dashboard/DashboardAside";
import useSlice from "../components/home/useHomeData";
import "../components/home/home.scss";

const overviewRefreshMs = 10_000;
const reportRefreshMs = 15_000;
const predictionRefreshMs = 3_000;
const noop = () => {};

export default function HomePage({
  user,
  onNavigate,
  onOpenReport,
  onSessionExpired = noop,
}: {
  user: { name: string; role: string };
  onNavigate: (page: string) => void;
  onOpenReport: (reportId: string) => void;
  onSessionExpired?: () => void;
}) {
  // 현장 점검자는 결재 내역을 보지 않는다. 결재 대기는 검토 권한이 있는 직책만 조회한다.
  const showApprovals = user.role !== "현장 점검자";
  const canReview = ["보전 팀장", "관제 담당자"].includes(user.role);
  const [tab, setTab] = useState<ApprovalTab>(canReview ? "review" : "mine");

  const overview = useSlice(
    listIncidentOverview,
    overviewRefreshMs,
    true,
    onSessionExpired,
  );
  const review = useSlice(
    () => listReports("review"),
    reportRefreshMs,
    canReview,
    onSessionExpired,
  );
  const mine = useSlice(
    () => listReports("mine"),
    reportRefreshMs,
    showApprovals,
    onSessionExpired,
  );
  const ml = useSlice(
    getMlPrediction,
    predictionRefreshMs,
    true,
    onSessionExpired,
  );

  const incidents = overview.data ?? [];
  const equipment = buildEquipmentRows(incidents);
  const active = activeIncidents(incidents);
  const needReport = active.filter((item) => !item.report_id).length;
  const counts = {
    경고: equipment.filter((row) => row.label === "경고").length,
    주의: equipment.filter((row) => row.label === "주의").length,
    정상: equipment.filter((row) => row.label === "정상").length,
  };
  const prediction = predictionView(ml);
  const level =
    prediction.probability === null
      ? null
      : probabilityTone(prediction.probability);
  const known = overview.data !== null;

  const openApprovals = () => {
    setTab("review");
    document
      .getElementById("home-approvals")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const summary = [
    {
      key: "equipment",
      label: "전체 설비",
      value: known ? `${equipment.length}` : "—",
      unit: known ? "대" : "",
      caption: known
        ? `경고 ${counts.경고} · 주의 ${counts.주의} · 정상 ${counts.정상}`
        : "불러오지 못했습니다",
    },
    {
      key: "incidents",
      label: "진행 중 이상",
      value: known ? `${active.length}` : "—",
      unit: known ? "건" : "",
      caption: known
        ? `보고서 작성 필요 ${needReport}건`
        : "불러오지 못했습니다",
      tone: active.length ? "danger" : undefined,
    },
    ...(canReview
      ? [
          {
            key: "review",
            label: "내 결재 대기",
            value: review.data ? `${review.data.length}` : "—",
            unit: review.data ? "건" : "",
            highlight: true,
            onClick: openApprovals,
          },
        ]
      : []),
    {
      key: "prediction",
      label: "향후 60초 에러 확률",
      value:
        prediction.probability === null ? "—" : percent(prediction.probability),
      unit: "",
      caption:
        prediction.probability === null
          ? prediction.notice || "예측을 표시할 수 없습니다"
          : level === "normal"
            ? "정상 범위"
            : `경고 기준 ${percent(prediction.threshold)} 이상`,
      tone: level && level !== "normal" ? "danger" : undefined,
    },
  ];

  return (
    <div className="home-page">
      <div className="home-page__header">
        <div>
          <PageTitle>대시보드</PageTitle>
        </div>
      </div>
      <div
        className="home-summary"
        style={
          { "--home-summary-count": summary.length } as React.CSSProperties
        }
        aria-label="요약"
      >
        {summary.map((item) => {
          const body = (
            <>
              <span className="home-summary__label">{item.label}</span>
              <strong data-tone={item.tone}>
                {item.value}
                {item.unit && <small>{item.unit}</small>}
              </strong>
              {item.caption && (
                <span className="home-summary__caption">{item.caption}</span>
              )}
            </>
          );
          return item.onClick ? (
            <button
              key={item.key}
              type="button"
              className={`home-summary__item ${item.highlight ? "is-highlight" : ""}`}
              onClick={item.onClick}
            >
              {body}
            </button>
          ) : (
            <div key={item.key} className="home-summary__item">
              {body}
            </div>
          );
        })}
      </div>
      <div className="home-grid home-grid--top">
        <EquipmentListCard
          overview={overview}
          onOpenEquipment={() => onNavigate("dashboard")}
        />
        <PredictionCard
          ml={ml}
          onOpenEquipment={() => onNavigate("dashboard")}
        />
      </div>
      {showApprovals && (
        <div className="home-grid home-grid--bottom">
          <ApprovalCard
            canReview={canReview}
            tab={tab}
            onTabChange={setTab}
            review={review}
            mine={mine}
            onOpenReport={onOpenReport}
            onNavigate={onNavigate}
          />
        </div>
      )}
    </div>
  );
}
