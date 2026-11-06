// LLM 사용량을 볼 수 있는 사람(#207). 백엔드 api/llm_usage.py의 can_view_usage와 같은 규칙이다.
// 계정 관리자이거나 직책이 관제 담당자. 규칙을 바꾸면 두 곳을 함께 고친다.
const USAGE_ROLES = new Set(["관제 담당자"]);

export function canViewLlmUsage(user: { role: string; is_admin: boolean }) {
  return user.is_admin || USAGE_ROLES.has(user.role);
}
