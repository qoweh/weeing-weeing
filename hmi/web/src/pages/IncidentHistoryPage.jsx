import { useEffect, useRef, useState } from 'react'
import { deleteIncident, getIncidentAnalysis, listIncidentApprovedReports, listIncidentOverview } from '../api/client'
import { AnalysisCard } from './IncidentTestPage'
import { pollAnalysis } from './incidentSimulation'
import '../components/ui/library.scss'
import './incident-test.scss'

function equipmentStatus(item) {
  if (item.recovered_at || item.status === 'RECOVERED') return '정상 회복'
  if (item.severity === 'Error' && ['OPEN', 'ACKNOWLEDGED'].includes(item.status)) return '이상 지속'
  return '회복 여부 확인 필요'
}
const reportStatuses = {
  DRAFT: '보고서 작성 중',
  SUBMITTED: '검토 대기',
  REVIEWED: '최종 승인 대기',
  REJECTED: '반려',
  APPROVED: '처리 완료',
}

function IncidentDeleteDialog({ incident, busy, error, onCancel, onConfirm }) {
  const dialog = useRef(null)
  const cancel = useRef(null)
  useEffect(() => {
    const element = dialog.current
    const previous = document.activeElement
    element.showModal()
    cancel.current?.focus()
    return () => { element.close(); previous?.focus() }
  }, [])
  return <dialog ref={dialog} className="incident-history-dialog incident-delete-dialog" aria-labelledby="incident-delete-title" aria-describedby="incident-delete-description" onCancel={(event) => { event.preventDefault(); if (!busy) onCancel() }}>
    <h2 id="incident-delete-title">이 사건을 삭제할까요?</h2>
    <p className="incident-delete-dialog__identity">{incident.codes.join(', ')} · {incident.incident_id}</p>
    <p id="incident-delete-description">연결된 모든 보고서와 결재 이력, AI 분석 결과와 보고서 검색 자료가 함께 삭제됩니다. 센서 원본 기록은 유지됩니다.</p>
    {incident.has_approved_report && <p className="incident-delete-dialog__warning">최종 승인된 보고서가 연결된 사건입니다.</p>}
    {error && <p className="incident-test__error" role="alert">{error}</p>}
    <div className="incident-history-dialog__actions"><button ref={cancel} type="button" disabled={busy} onClick={onCancel}>취소</button><button className="incident-delete-dialog__confirm" type="button" disabled={busy} onClick={onConfirm}>{busy ? '삭제 중…' : '사건 삭제'}</button></div>
  </dialog>
}

function IncidentDetailDialog({ incident, result, reports, onRefresh, onClose, onOpenDraft, onOpenReport, onDelete, canWrite, busy }) {
  const dialog = useRef(null)
  const closeButton = useRef(null)
  useEffect(() => {
    const element = dialog.current
    const previousFocus = document.activeElement
    element.showModal()
    closeButton.current?.focus()
    return () => { element.close(); previousFocus?.focus() }
  }, [])

  return <dialog ref={dialog} className="incident-history-dialog" aria-labelledby="incident-detail-title" onCancel={(event) => { event.preventDefault(); onClose() }}>
    <div className="incident-history__detail"><div><p className="incident-history-dialog__eyebrow">INCIDENT ANALYSIS</p><h2 id="incident-detail-title">사건 분석 결과</h2></div><button ref={closeButton} type="button" className="incident-history-dialog__close" onClick={onClose} aria-label="사건 분석 결과 닫기">×</button></div>
    <AnalysisCard incident={incident} result={result} />
    {incident.has_approved_report && <section className="incident-history-dialog__reports" aria-label="최종 승인 보고서"><h3>최종 승인 보고서</h3>
      {!reports ? <p role="status">보고서를 불러오는 중입니다.</p> : reports.error ? <p className="incident-test__error" role="alert">{reports.error}</p> : reports.items.length === 0 ? <p>승인된 보고서를 찾을 수 없습니다. 목록을 새로고침해 주세요.</p> : <ul>{reports.items.map((report) => <li key={report.report_id}><button type="button" disabled={busy} onClick={() => onOpenReport(report.report_id, incident.incident_id, report.report_version)}><span><strong>{report.report_id}</strong><small>v{report.report_version} · {report.author_name}</small></span><span aria-hidden="true">→</span></button></li>)}</ul>}
    </section>}
    <div className="incident-history-dialog__actions">{onDelete && <button className="incident-delete-dialog__trigger" type="button" onClick={onDelete} disabled={busy}>사건 삭제</button>}<button type="button" onClick={onRefresh} disabled={busy}>결과 새로고침</button><button type="button" onClick={onClose} disabled={busy}>닫기</button>{!incident.has_approved_report && incident.report_id && <button type="button" disabled={busy} onClick={() => onOpenReport(incident.report_id, incident.incident_id)}>보고서 확인</button>}{!incident.report_id && canWrite && <button type="button" disabled={busy || !result || Boolean(result.error) || ['PENDING', 'RUNNING'].includes(result.job?.status)} onClick={() => onOpenDraft(incident.incident_id, result?.analysis)}>보고서 초안 작성</button>}</div>
    {!incident.report_id && canWrite && (!result || ['PENDING', 'RUNNING'].includes(result.job?.status)) && <p className="incident-result__note">분석 상태를 확인하거나 분석이 끝난 뒤 작성할 수 있습니다.</p>}
  </dialog>
}

function IncidentTable({ title, items, onSelect, active = false }) {
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(false)
  const [sort, setSort] = useState({ key: 'first_detected_at', direction: -1 })
  const columns = [['number', '번호'], ['codes', '사건'], ['asset_id', '설비 모델'], ['first_detected_at', '발생 시각'], ['equipment', '설비 상태'], ['processing', '처리 상태'], ['incident_id', '사건 번호']]
  const sorted = [...items].sort((a, b) => {
    if (sort.key === 'number') return (String(b.first_detected_at).localeCompare(String(a.first_detected_at))) * sort.direction * -1
    return String(a[sort.key] ?? '').localeCompare(String(b[sort.key] ?? ''), 'ko', { numeric: true }) * sort.direction
  })
  const pageSize = active && !expanded ? 3 : 10
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize))
  const current = Math.min(page, pages)
  const rows = active && !expanded ? sorted.slice(0, 3) : sorted.slice((current - 1) * pageSize, current * pageSize)
  return <section className="library-section library-section--compact incident-history__section" aria-label={title}>
    <div className="library-summary"><h2>{title} <span>{items.length}건</span></h2><p>열 제목을 클릭하여 오름차순 / 내림차순 정렬</p></div>
    <div className="library-table-scroll" role="region" aria-label={`${title} 표`} tabIndex={0}>
      <table className="library-table incident-history__library-table"><thead><tr>{columns.map(([key, label]) => <th key={key} aria-sort={sort.key === key ? (sort.direction === 1 ? 'ascending' : 'descending') : 'none'}><button type="button" onClick={() => { setSort({ key, direction: sort.key === key ? -sort.direction : 1 }); setPage(1) }}>{label}{sort.key === key && <span aria-hidden="true"> {sort.direction === 1 ? '↑' : '↓'}</span>}</button></th>)}</tr></thead>
        <tbody>{rows.map((item, index) => <tr key={item.incident_id}><td>{String((current - 1) * pageSize + index + 1).padStart(2, '0')}</td><td><button type="button" className="library-link" onClick={() => onSelect(item)}>{item.codes.join(', ')}</button></td><td>{item.asset_id}</td><td>{new Date(item.first_detected_at).toLocaleString('ko-KR')}</td><td>{item.equipment}</td><td><span className={`library-status library-status--${item.report_status === 'REJECTED' ? 'danger' : active ? 'warning' : 'success'}`}>{item.processing}</span></td><td>{item.incident_id}</td></tr>)}
          {!rows.length && <tr><td className="library-empty" colSpan={columns.length}>표시할 사건이 없습니다.</td></tr>}</tbody></table>
    </div>
    {active && items.length > 3 && <div className="incident-history__more"><button type="button" onClick={() => { setExpanded(!expanded); setPage(1) }}>{expanded ? '접기' : `전체 ${items.length}건 보기`}</button></div>}
    {(!active || expanded) && <div className="library-pagination"><button type="button" aria-label={`${title} 이전 페이지`} disabled={current === 1} onClick={() => setPage(current - 1)}>‹</button><span>{current} / {pages}</span><button type="button" aria-label={`${title} 다음 페이지`} disabled={current === pages} onClick={() => setPage(current + 1)}>›</button></div>}
  </section>
}

export default function IncidentHistoryPage({ onSessionExpired, onOpenDraft, onOpenReport, onBusyChange, user, busy }) {
  const [incidents, setIncidents] = useState([])
  const [selected, setSelected] = useState(null)
  const [result, setResult] = useState(null)
  const [reports, setReports] = useState(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let active = true
    listIncidentOverview().then((items) => {
      if (active) setIncidents(items.map(({ incident, has_approved_report, report_status, report_id }) => ({
        ...incident, has_approved_report, report_id, report_status, equipment: equipmentStatus(incident), processing: report_status ? (reportStatuses[report_status] || report_status) : '보고서 미작성',
      })))
    }).catch((failure) => {
      if (!active) return
      setError(failure.message)
      if (failure.status === 401) onSessionExpired()
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [reload, onSessionExpired])

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    async function load() {
      try {
        const initial = await getIncidentAnalysis(selected.incident_id)
        if (controller.signal.aborted) return
        setResult(initial)
        if (['PENDING', 'RUNNING'].includes(initial.job?.status)) {
          await pollAnalysis(selected.incident_id, getIncidentAnalysis, controller.signal, setResult)
        }
      } catch (failure) {
        if (controller.signal.aborted || failure.name === 'AbortError') return
        if (failure.status === 401) onSessionExpired()
        setResult({ error: failure.message })
      }
    }
    load()
    return () => controller.abort()
  }, [selected, onSessionExpired])

  useEffect(() => {
    if (!selected?.has_approved_report) return
    let cancelled = false
    listIncidentApprovedReports(selected.incident_id).then((items) => {
      if (!cancelled) setReports({ items })
    }).catch((failure) => {
      if (cancelled) return
      if (failure.status === 401) onSessionExpired()
      setReports({ error: failure.message })
    })
    return () => { cancelled = true }
  }, [selected, onSessionExpired])

  function refresh() { setLoading(true); setError(''); setReload((value) => value + 1) }
  async function removeIncident() {
    if (!deleteTarget || deleteBusy) return
    setDeleteBusy(true); onBusyChange(true); setDeleteError('')
    try {
      await deleteIncident(deleteTarget.incident_id)
      setNotice('사건과 연결된 자료를 삭제했습니다.')
      setDeleteTarget(null); setSelected(null); refresh()
    } catch (failure) {
      if (failure.status === 401) onSessionExpired()
      else setDeleteError(failure.message)
    } finally {
      setDeleteBusy(false); onBusyChange(false)
    }
  }
  // 같은 사건을 다시 눌러도 새 조회를 시작한다. 기존 객체 그대로 설정하면
  // React가 선택 변경을 감지하지 못해 결과만 지워질 수 있다.
  function select(item) { setResult(null); setReports(null); setSelected({ ...item }) }
  const term = query.trim().toLowerCase()
  const visible = incidents.filter((item) => [item.incident_id, item.asset_id, ...item.codes].some((value) => value?.toLowerCase().includes(term)))

  return <div className="library-page incident-history" aria-label="이상 현황">
    <h1 className="incident-history__title">이상현황</h1>
    <div className="incident-history__toolbar"><label className="incident-history__search"><span className="incident-history__sr-only">사건 검색</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="⌕  에러 코드, 설비 ID, 사건 번호 검색" /></label><button type="button" onClick={refresh} disabled={loading}>목록 새로고침</button></div>
    {notice && <p role="status">{notice}</p>}
    {loading ? <p role="status">사건을 불러오는 중입니다.</p> : error ? <p className="incident-test__error" role="alert">{error} <button type="button" onClick={refresh}>다시 시도</button></p> : <>
      <IncidentTable title="처리 중인 사건" items={visible.filter((item) => !item.has_approved_report)} onSelect={select} active />
      <IncidentTable title="처리 완료된 사건" items={visible.filter((item) => item.has_approved_report)} onSelect={select} />
      <p className="incident-result__note">최근 Error 사건 최대 100건을 표시합니다. 보고서 최종 승인 여부로 처리 상태를 구분합니다.</p>
    </>}
    {selected && <IncidentDetailDialog incident={selected} result={result} reports={reports} onRefresh={() => select(selected)} onClose={() => setSelected(null)} onOpenDraft={onOpenDraft} onOpenReport={onOpenReport} onDelete={user.role === '관제 담당자' ? () => { setDeleteError(''); setDeleteTarget(selected) } : undefined} busy={busy} canWrite={['현장 점검자', '보전 팀장'].includes(user.role)} />}
    {deleteTarget && <IncidentDeleteDialog incident={deleteTarget} busy={deleteBusy} error={deleteError} onCancel={() => setDeleteTarget(null)} onConfirm={removeIncident} />}
  </div>
}
