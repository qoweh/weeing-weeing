import { useEffect, useState } from 'react'
import { listReports, listIncidents, listReviewHistory } from '../api/client'
import Button from '../components/ui/Button'
import { Filters, LibraryTable } from '../components/ui/library'
import { filterRows } from '../components/ui/libraryUtils'

const labels = {
  DRAFT: '임시 저장',
  SUBMITTED: '검토 중',
  REVIEWED: '최종 승인 대기',
  APPROVED: '최종 승인',
  REJECTED: '반려',
}
const descriptions = {
  mine: '내가 작성한 보고서와 진행 상태를 확인합니다.',
  review: '내가 검토하거나 승인해야 하는 보고서입니다.',
  history: '보고서별 내 최근 처리와 현재 상태를 확인합니다. 이전 처리는 각 버전에서 확인할 수 있습니다.',
  approved: '최종 승인된 전체 보고서를 확인합니다.',
}
const emptyMessages = {
  mine: '표시할 내 보고서가 없습니다.',
  review: '결재 대기 중인 보고서가 없습니다.',
  history: '처리한 결재 이력이 없습니다.',
  approved: '표시할 정비 이력이 없습니다.',
}

export default function MaintenancePage({ user, busy, selectedTab, onSelectTab, onOpen, onSessionExpired }) {
  const canWrite = ['현장 점검자', '보전 팀장'].includes(user.role)
  const canReview = ['보전 팀장', '관제 담당자'].includes(user.role)
  const tabs = [
    ...(canWrite ? [{ id: 'mine', label: '내 보고서' }] : []),
    ...(canReview ? [{ id: 'review', label: '결재 대기' }, { id: 'history', label: '내 결재 이력' }] : []),
    { id: 'approved', label: '정비 이력' },
  ]
  const activeTab = tabs.some((tab) => tab.id === selectedTab) ? selectedTab : tabs[0].id
  const [reportsByTab, setReportsByTab] = useState({ mine: [], review: [], history: [], approved: [] })
  const [incidents, setIncidents] = useState([])
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState({ period: '', docType: '' })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let active = true
    Promise.all([
      canWrite ? listReports('mine') : Promise.resolve([]),
      canReview ? listReports('review') : Promise.resolve([]),
      canReview ? listReviewHistory() : Promise.resolve([]),
      listReports('approved'),
      listIncidents(),
    ])
      .then(([mine, review, history, approved, availableIncidents]) => {
        if (!active) return
        setReportsByTab({ mine, review, history, approved })
        setIncidents(availableIncidents)
      })
      .catch((failure) => {
        if (!active) return
        setError(failure.message)
        if (failure.status === 401) onSessionExpired()
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [reload, onSessionExpired, canWrite, canReview])

  function refresh() {
    setLoading(true)
    setError('')
    setReload((value) => value + 1)
  }

  function moveTab(event, index) {
    let next
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = tabs.length - 1
    else return
    event.preventDefault()
    onSelectTab(tabs[next].id)
    event.currentTarget.parentElement.querySelectorAll('[role="tab"]')[next]?.focus()
  }

  const rows = reportsByTab[activeTab].map((entry) => {
    const report = activeTab === 'history' ? entry.report : entry
    const incident = incidents.find((item) => item.incident_id === report.incident_id)
    return {
      id: report.report_id,
      rowKey: activeTab === 'history' ? `${report.report_id}:${entry.review_version}:${entry.review_step}` : report.report_id,
      name: report.report_id,
      reviewVersion: entry.review_version,
      reviewAction: activeTab === 'history' ? `v${entry.review_version} ${entry.decision === '반려' ? '반려' : entry.review_role === '보전 팀장' ? '검토 승인' : '최종 승인'}` : '',
      reviewedAt: entry.reviewed_at,
      currentVersion: report.report_version,
      reportVersion: report.report_version,
      issue: incident?.codes?.join(', ') || report.incident_id || '사건 미연결',
      incidentId: report.incident_id,
      asset: report.asset_id,
      date: incident?.first_detected_at,
      author: report.author_name,
      isOwn: activeTab === 'approved' && report.author_id === user.employee_no,
      status: labels[report.report_status] || report.report_status,
      tone: report.report_status === 'APPROVED' ? 'success'
        : report.report_status === 'REJECTED' ? 'danger'
          : ['SUBMITTED', 'REVIEWED'].includes(report.report_status) ? 'warning' : 'neutral',
    }
  })

  return (
    <div className="library-page" aria-label="정비 이력 · 보고서">
      {canWrite && <div className="maintenance-actions">
        <Button className="maintenance-create" disabled={busy} onClick={() => onOpen()}>새 보고서 작성</Button>
      </div>}
      <div className="maintenance-tabs" role="tablist" aria-label="보고서 목록">
        {tabs.map((tab, index) => <button
          key={tab.id}
          id={`maintenance-tab-${tab.id}`}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          aria-controls={`maintenance-panel-${tab.id}`}
          tabIndex={activeTab === tab.id ? 0 : -1}
          className={`maintenance-tab ${activeTab === tab.id ? 'maintenance-tab--active' : ''}`}
          onClick={() => onSelectTab(tab.id)}
          onKeyDown={(event) => moveTab(event, index)}
        >
          {tab.label}<span className="maintenance-tab__count">{loading || error ? '—' : reportsByTab[tab.id].length}</span>
        </button>)}
      </div>
      {tabs.map((tab) => <section key={tab.id} role="tabpanel" id={`maintenance-panel-${tab.id}`} aria-labelledby={`maintenance-tab-${tab.id}`} hidden={activeTab !== tab.id} tabIndex={0}>
        {activeTab === tab.id && <>
        <p className="maintenance-description">{descriptions[activeTab]}</p>
        <Filters report query={query} setQuery={setQuery} filters={filters} setFilters={setFilters} onRefresh={refresh} loading={loading} />
        {loading ? <p role="status">보고서 목록을 불러오는 중입니다.</p>
          : error ? <p className="workspace-error" role="alert">{error} <Button onClick={refresh}>다시 시도</Button></p>
            : <>
              <LibraryTable
                key={activeTab}
                report
                history={activeTab === 'history'}
                title={tabs.find((tab) => tab.id === activeTab).label}
                rows={filterRows(rows, query, filters)}
                emptyMessage={query.trim() || filters.period ? '검색 조건에 맞는 보고서가 없습니다.' : emptyMessages[activeTab]}
                onOpen={(row, version) => onOpen(row.id, undefined, version ?? (activeTab === 'approved' ? row.reportVersion : undefined))}
              />
              <p className="library-footnote">각 목록은 최근 조회된 항목 최대 100건을 표시합니다. 사건 정보가 조회 범위에 없으면 발생 시각을 —로 표시합니다.</p>
            </>}
        </>}
      </section>)}
    </div>
  )
}
