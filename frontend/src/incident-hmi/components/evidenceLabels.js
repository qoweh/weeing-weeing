export function evidenceLabel(item) {
  if (!item) return "출처 정보 확인 필요";
  const page = Number.isInteger(item.page) && item.page > 0 ? item.page : null;
  if (!page && !item.title && item.citation) return item.citation;
  const parts = [item.title || item.doc_id || "문서"];
  if (item.doc_version) parts.push(`v${item.doc_version}`);
  if (page) parts.push(`PDF ${page}쪽`);
  if (item.section) parts.push(item.section);
  if (item.citation?.includes("가상 사례") && !parts[0].includes("가상 사례"))
    parts.push("가상 사례");
  return parts.join(" · ");
}

export function referenceLabels(ids = [], evidence = []) {
  const sources = new Map(evidence.map((item) => [item.evidence_id, item]));
  return [...new Set(ids.map((id) => evidenceLabel(sources.get(id))))];
}
