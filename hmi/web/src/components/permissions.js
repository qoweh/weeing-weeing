// 화면의 직책 권한 규칙. 백엔드(api/auth.py require_roles, db/reports.py)와 같다.
// 계정 관리자(is_admin)는 직책과 관계없이 모든 직책 권한을 가진다(D-36).
// 서버가 최종 판단하므로 여기서는 버튼·메뉴를 보일지만 정한다. frontend/src/components/auth/permissions.ts와 같은 규칙이다.
export const CONTROL = '관제 담당자'
export const MAINT_LEAD = '보전 팀장'
export const INSPECTOR = '현장 점검자'

const hasRole = (user, roles) => Boolean(user && (user.is_admin || roles.includes(user.role)))

export const canControl = (user) => hasRole(user, [CONTROL])
export const canWriteReports = (user) => hasRole(user, [INSPECTOR, MAINT_LEAD])
export const canReviewReports = (user) => hasRole(user, [MAINT_LEAD, CONTROL])
export const canRunAnalysis = (user) => hasRole(user, [CONTROL, MAINT_LEAD, INSPECTOR])

export function reviewStep(user, status) {
  if (status === 'SUBMITTED' && hasRole(user, [MAINT_LEAD])) return 'review'
  if (status === 'REVIEWED' && hasRole(user, [CONTROL])) return 'approve'
  return null
}
