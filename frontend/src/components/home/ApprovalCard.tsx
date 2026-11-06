import type { ReportSummary } from "../../api/client";
import type { Slice } from "./useHomeData";
import Glyph from "../ui/Glyph";
import HomeCard, { HomeBadge, HomeNotice, type HomeTone } from "./HomeCard";
import { formatDate } from "./homeData";

export type ApprovalTab = "review" | "mine";
const limit = 3;
const statusLabels: Record<string, string> = {
  DRAFT: "임시 저장",
  SUBMITTED: "검토 대기",
  REVIEWED: "최종 결재 대기",
  APPROVED: "승인",
  REJECTED: "반려",
};
const statusTones: Record<string, HomeTone> = {
  DRAFT: "info",
  SUBMITTED: "warning",
  REVIEWED: "warning",
  APPROVED: "success",
  REJECTED: "danger",
};

export default function ApprovalCard({
  canReview,
  tab,
  onTabChange,
  review,
  mine,
  onOpenReport,
  onNavigate,
}: {
  canReview: boolean;
  tab: ApprovalTab;
  onTabChange: (tab: ApprovalTab) => void;
  review: Slice<ReportSummary[]>;
  mine: Slice<ReportSummary[]>;
  onOpenReport: (reportId: string) => void;
  onNavigate: (page: string) => void;
}) {
  const current = canReview && tab === "review" ? review : mine;
  const showing: ApprovalTab =
    canReview && tab === "review" ? "review" : "mine";
  const items = [...(current.data ?? [])]
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
    .slice(0, limit);
  const tabs: { id: ApprovalTab; label: string }[] = [
    ...(canReview
      ? [
          {
            id: "review" as const,
            label: `결재 대기${review.data ? ` ${review.data.length}` : ""}`,
          },
        ]
      : []),
    { id: "mine", label: "내 보고서" },
  ];
  return (
    <HomeCard
      id="home-approvals"
      title="결재 내역"
      aside={
        <div className="home-tabs" role="group" aria-label="결재 내역 구분">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={showing === item.id}
              onClick={() => onTabChange(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      }
      className="home-card--approvals"
    >
      {current.loading ? (
        <HomeNotice>보고서를 불러오는 중입니다.</HomeNotice>
      ) : current.data === null ? (
        <HomeNotice
          tone="danger"
          action={
            <button
              type="button"
              className="home-retry"
              onClick={current.reload}
            >
              다시 시도
            </button>
          }
        >
          보고서를 불러오지 못했습니다.
        </HomeNotice>
      ) : items.length === 0 ? (
        <HomeNotice>
          {showing === "review"
            ? "결재 대기 중인 보고서가 없습니다."
            : "작성한 보고서가 없습니다."}
        </HomeNotice>
      ) : (
        <ul className="home-list">
          {items.map((report, index) => (
            <li key={report.report_id}>
              <button
                type="button"
                className={`home-list__item ${index === 0 && showing === "review" ? "is-first" : ""}`}
                onClick={() => onOpenReport(report.report_id)}
              >
                <span className="home-list__text">
                  <strong>{report.report_id}</strong>
                  <small>
                    {report.asset_id || "설비 미지정"}
                    {report.author_name
                      ? ` · ${report.author_name}`
                      : ""} · {formatDate(report.updated_at)}
                  </small>
                </span>
                <HomeBadge
                  tone={statusTones[report.report_status] ?? "neutral"}
                >
                  {statusLabels[report.report_status] ?? report.report_status}
                </HomeBadge>
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        className="home-link home-link--end"
        onClick={() => onNavigate("maintenance")}
      >
        정비이력에서 전체 보기 <Glyph name="chevron-right" />
      </button>
    </HomeCard>
  );
}
