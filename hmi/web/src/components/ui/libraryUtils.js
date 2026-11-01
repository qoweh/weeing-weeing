export function filterRows(rows, query, filters) {
  return rows.filter(
    (r) =>
      (!query.trim() ||
        [r.name, r.asset, r.issue, r.incidentId, r.author].some((v) =>
          String(v ?? '')
            .toLowerCase()
            .includes(query.trim().toLowerCase()),
        )) &&
      (!filters.docType || filters.docType === 'all' || r.doc_type === filters.docType) &&
      (!filters.period ||
        (r.date &&
          new Date(r.date).getTime() >=
            Date.now() - Number(filters.period) * 86400000)),
  )
}
export function dateLabel(value, time = false) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '—'
    : new Intl.DateTimeFormat('ko-KR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        ...(time ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
      }).format(date)
}
