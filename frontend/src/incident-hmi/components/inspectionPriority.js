// 과거 likelihood는 점검 우선순위가 아니므로 자동 변환하지 않는다.
export function inspectionPriorityLabel(candidate) {
  return ["우선 확인", "후속 확인"].includes(candidate.inspection_priority)
    ? candidate.inspection_priority
    : "점검 우선순위 미지정";
}
