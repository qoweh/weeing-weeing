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
import PredictionCard from "../components/home/PredictionCard";
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

  return (
    <div className="home-page">
      <div className="home-page__header">
        <div>
          <PageTitle>대시보드</PageTitle>
        </div>
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
