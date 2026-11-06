import type { Slice } from "./useHomeData";
import type { IncidentOverview } from "../../api/client";
import Glyph from "../ui/Glyph";
import HomeCard, { HomeBadge, HomeNotice } from "./HomeCard";
import {
  buildEquipmentRows,
  formatDateTime,
  type EquipmentRow,
} from "./homeData";

// 화면 확인용 더미 설비. 실제 설비 목록 API가 생기면 지운다.
const dummyRows: EquipmentRow[] = [
  {
    id: "BLDC-002",
    name: "모터 구동 롤러 컨베이어",
    label: "주의",
    tone: "warning",
    openCount: 1,
    latest: "2026-11-05T17:42:00+09:00",
  },
  {
    id: "BLDC-003",
    name: "포장 라인 벨트 컨베이어",
    label: "정상",
    tone: "success",
    openCount: 0,
    latest: "2026-10-29T13:05:00+09:00",
  },
];

export default function EquipmentListCard({
  overview,
  onOpenEquipment,
}: {
  overview: Slice<IncidentOverview[]>;
  onOpenEquipment: (assetId: string) => void;
}) {
  const realRows = buildEquipmentRows(overview.data ?? []);
  const rows = [
    ...realRows,
    ...dummyRows.filter(
      (dummy) => !realRows.some((row) => row.id === dummy.id),
    ),
  ];
  const isDummy = (id: string) => dummyRows.some((row) => row.id === id);
  // 사건 조회가 실패해도 확정된 설비는 보이되, 상태를 믿을 수 없으니 안내한다.
  const unreliable = overview.data === null && !!overview.error;
  return (
    <HomeCard
      id="home-equipment"
      title="설비 리스트"
      aside={<span className="home-card__count">전체 {rows.length}대</span>}
      className="home-card--equipment"
    >
      {overview.loading ? (
        <HomeNotice>설비 정보를 불러오는 중입니다.</HomeNotice>
      ) : (
        <>
          {overview.error && (
            <HomeNotice
              tone="danger"
              action={
                <button
                  type="button"
                  className="home-retry"
                  onClick={overview.reload}
                >
                  다시 시도
                </button>
              }
            >
              {unreliable
                ? "설비 상태를 불러오지 못했습니다."
                : "최신 상태를 불러오지 못해 이전 정보를 표시합니다."}
            </HomeNotice>
          )}
          {rows.length === 0 ? (
            <HomeNotice>등록된 설비가 없습니다.</HomeNotice>
          ) : (
            <div className="home-table" role="table" aria-label="설비 목록">
              <div className="home-table__head" role="row">
                <span role="columnheader">설비</span>
                <span role="columnheader">상태</span>
                <span role="columnheader">진행 중 이상</span>
                <span role="columnheader">최근 이상 발생</span>
                <span role="columnheader" className="home-sr-only">
                  이동
                </span>
              </div>
              {rows.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  role="row"
                  className="home-table__row"
                  onClick={() => {
                    if (!isDummy(row.id)) onOpenEquipment(row.id);
                  }}
                  aria-label={`${row.name} ${row.id} 상세 보기`}
                >
                  <span role="cell" className="home-table__name">
                    <strong>{row.name}</strong>
                    <small>{row.id}</small>
                  </span>
                  <span role="cell">
                    <HomeBadge tone={unreliable ? "neutral" : row.tone}>
                      {unreliable ? "확인 불가" : row.label}
                    </HomeBadge>
                  </span>
                  <span
                    role="cell"
                    className={
                      row.openCount ? "home-table__alert" : "home-table__muted"
                    }
                  >
                    {unreliable ? "—" : `${row.openCount}건`}
                  </span>
                  <span role="cell" className="home-table__muted">
                    {formatDateTime(row.latest)}
                  </span>
                  <span role="cell" aria-hidden="true" className="home-chevron">
                    <Glyph name="chevron-right" size={18} />
                  </span>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </HomeCard>
  );
}
