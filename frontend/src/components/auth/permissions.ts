// 화면의 직책 권한 규칙. 백엔드(api/auth.py require_roles, db/reports.py)와 같다.
// 계정 관리자(is_admin)는 직책과 관계없이 모든 직책 권한을 가진다(D-36).
// 서버가 최종 판단하므로 여기서는 버튼·메뉴를 보일지만 정한다.

export type PermissionUser =
  { role: string; is_admin?: boolean | null } | null | undefined;

export const CONTROL = "관제 담당자";
export const MAINT_LEAD = "보전 팀장";
export const INSPECTOR = "현장 점검자";

function hasRole(user: PermissionUser, roles: string[]) {
  return Boolean(user && (user.is_admin || roles.includes(user.role)));
}

/** 관제 담당자 업무: 문서 등록·삭제, 사건 삭제, 최종 승인된 보고서 삭제. */
export const canControl = (user: PermissionUser) => hasRole(user, [CONTROL]);

/** 보고서 작성·제출·개정(본인 보고서). */
export const canWriteReports = (user: PermissionUser) =>
  hasRole(user, [INSPECTOR, MAINT_LEAD]);

/** 결재 대기 목록·내 결재 이력. */
export const canReviewReports = (user: PermissionUser) =>
  hasRole(user, [MAINT_LEAD, CONTROL]);

/** AI 사건 분석 실행·재시도. */
export const canRunAnalysis = (user: PermissionUser) =>
  hasRole(user, [CONTROL, MAINT_LEAD, INSPECTOR]);

/** 보고서 상태에 맞춰 이 사용자가 할 수 있는 결재 단계. 없으면 null. */
export function reviewStep(
  user: PermissionUser,
  status: string | null | undefined,
): "review" | "approve" | null {
  if (status === "SUBMITTED" && hasRole(user, [MAINT_LEAD])) return "review";
  if (status === "REVIEWED" && hasRole(user, [CONTROL])) return "approve";
  return null;
}
