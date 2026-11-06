import type { IncidentOverview } from "../../api/client";
import {
  knownEquipmentIds,
  reportEquipmentName,
} from "../report/reportPresentation";
import { activeStatuses } from "../dashboard/DashboardAside";
import type { HomeTone } from "./HomeCard";

export type EquipmentRow = {
  id: string;
  name: string;
  label: "경고" | "주의" | "정상";
  tone: HomeTone;
  openCount: number;
  latest: string | null;
};

// 아직 접수되지 않은 사건(OPEN)을 먼저, 같은 상태에서는 최근 발생한 사건을 먼저 둔다.
export function sortByUrgency(a: IncidentOverview, b: IncidentOverview) {
  const rank = (item: IncidentOverview) => {
    const index = activeStatuses.indexOf(item.incident.status);
    return index < 0 ? activeStatuses.length : index;
  };
  return (
    rank(a) - rank(b) ||
    String(b.incident.first_detected_at).localeCompare(
      String(a.incident.first_detected_at),
    )
  );
}

export function activeIncidents(overview: IncidentOverview[]) {
  return overview
    .filter((item) => activeStatuses.includes(item.incident.status))
    .sort(sortByUrgency);
}

/**
 * 설비 목록 API가 아직 없어, 프로젝트에서 확정한 설비와 사건에 나온 설비를 합쳐 만든다.
 * 상태는 진행 중인 사건의 심각도로 정한다(Error=경고, Warning=주의).
 */
export function buildEquipmentRows(overview: IncidentOverview[]) {
  const ids = new Set<string>(knownEquipmentIds());
  for (const item of overview) {
    if (item.incident.asset_id) ids.add(item.incident.asset_id);
  }
  const active = activeIncidents(overview);
  const rows: EquipmentRow[] = [...ids].map((id) => {
    const open = active.filter((item) => item.incident.asset_id === id);
    const all = overview.filter((item) => item.incident.asset_id === id);
    const hasError = open.some((item) => item.incident.severity === "Error");
    const latest =
      all
        .map((item) => String(item.incident.first_detected_at))
        .sort()
        .at(-1) ?? null;
    return {
      id,
      name: reportEquipmentName(id) || id,
      label: hasError ? "경고" : open.length ? "주의" : "정상",
      tone: hasError ? "danger" : open.length ? "warning" : "success",
      openCount: open.length,
      latest,
    };
  });
  const rank = { 경고: 0, 주의: 1, 정상: 2 } as const;
  return rows.sort(
    (a, b) => rank[a.label] - rank[b.label] || a.id.localeCompare(b.id),
  );
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "날짜 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "날짜 없음";
  return date.toLocaleDateString("ko-KR");
}
