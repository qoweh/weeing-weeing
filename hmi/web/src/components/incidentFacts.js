// 서버가 만든 사건 정보 헤더만 바꾸고 AI의 다른 문장과 저장된 원본은 건드리지 않는다.
export function displayIncidentFacts(text, incident) {
  if (typeof text !== 'string' || !incident?.incident_id) return text
  const header = `사건:\n사건 ID: ${incident.incident_id}`
  if (!text.startsWith(`${header}\n`) && text !== header) return text
  return `사건번호: ${incident.incident_number || '확인되지 않음'}${text.slice(header.length)}`
}

export function candidateBasis(basis, observedFacts) {
  const normalize = (value) => typeof value === 'string' ? value.replace(/\r\n/g, '\n').trim() : ''
  const common = normalize(observedFacts)
  return common && normalize(basis) === common ? '' : basis
}
