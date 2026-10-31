import { useEffect, useState } from 'react'
import { listReports, listIncidents } from '../api/client'
import Button from '../components/ui/Button'
import { Filters, filterRows, LibraryTable } from '../components/ui/library'
const labels = {
  DRAFT: '임시 저장',
  SUBMITTED: '검토 중',
  REVIEWED: '검토 승인',
  APPROVED: '작성 완료',
  REJECTED: '반려',
}
export default function MaintenancePage({ user, onOpen, onSessionExpired, refreshKey = 0 }) {
  const [rows, setRows] = useState([]),
    [issues, setIssues] = useState([])
  const [query, setQuery] = useState(''),
    [filters, setFilters] = useState({ period: '', docType: '' })
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [reload, setReload] = useState(0)
  const [scope, setScope] = useState('all')
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    Promise.all([listReports(scope), listIncidents()])
      .then(([reports, incidents]) => {
        if (!active) return
        const mapped = reports.map((r) => {
          const incident = incidents.find(
            (i) => i.incident_id === r.incident_id,
          )
          return {
            id: r.report_id,
            reportId: r.report_id,
            incidentId: r.incident_id,
            name: r.report_id,
            issue: incident?.codes?.join(', ') || r.incident_id || '사건 미연결',
            asset: r.asset_id,
            date: incident?.first_detected_at || r.updated_at,
            author: r.author_name,
            incident,
            status: labels[r.report_status] || r.report_status,
            tone:
              r.report_status === 'APPROVED'
                ? 'success'
                : ['SUBMITTED', 'REVIEWED'].includes(r.report_status)
                  ? 'warning'
                  : 'neutral',
          }
        })
        setRows(mapped)
        setIssues(
          incidents
            .filter((i) => ['OPEN', 'ACKNOWLEDGED'].includes(i.status) && i.severity === 'Error')
            .map((i) => {
              const report = reports.find(
                (r) => r.incident_id === i.incident_id,
              )
              return {
                id: report?.report_id || i.incident_id,
                reportId: report?.report_id,
                incidentId: i.incident_id,
                name: report?.report_id || '보고서 작성',
                issue: i.codes.join(', '),
                asset: i.asset_id,
                date: i.first_detected_at,
                author: report?.author_name || '—',
                status: report ? labels[report.report_status] : '작성 필요',
                tone: 'warning',
                incident: i,
              }
            }),
        )
      })
      .catch((e) => {
        if (active) {
          setError(e.message)
          if (e.status === 401) onSessionExpired()
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [scope, reload, refreshKey, onSessionExpired])
  return (
    <div className="library-page" aria-label="정비 이력 · 보고서">
      <div className="library-report-scopes" role="group" aria-label="보고서 목록 선택">
        <Button aria-pressed={scope === 'all'} onClick={() => setScope('all')}>전체 보고서</Button>
        <Button aria-pressed={scope === 'mine'} onClick={() => setScope('mine')}>내 보고서</Button>
        {['보전 팀장', '관제 담당자'].includes(user.role) && (
          <Button aria-pressed={scope === 'review'} onClick={() => setScope('review')}>결재 대기</Button>
        )}
      </div>
      <Filters
        report
        query={query}
        setQuery={setQuery}
        filters={filters}
        setFilters={setFilters}
        onRefresh={() => setReload((n) => n + 1)}
        loading={loading}
      />
      {loading ? (
        <p role="status">정비 이력을 불러오는 중입니다.</p>
      ) : (
        <>
          {error && (
            <p className="workspace-error" role="alert">
              실제 목록을 불러오지 못했습니다: {error}{' '}
              <Button onClick={() => setReload((n) => n + 1)}>다시 시도</Button>
            </p>
          )}
          {scope === 'all' && <LibraryTable
            report
            compact
            title="오류 이슈"
            rows={filterRows(issues, query, filters)}
            onOpen={(r) => onOpen(r.reportId, r.incidentId, r)}
          />}
          <LibraryTable
            report
            title={{ all: '정비 이력', mine: '내 보고서', review: '결재 대기' }[scope]}
            rows={filterRows(rows, query, filters)}
            onOpen={(r) => onOpen(r.reportId || r.id, r.incidentId, r)}
          />
          <p className="library-footnote">
            최근 조회된 사건·보고서 기준입니다. 발생 시각이 없는 항목은 —로
            표시합니다.
          </p>
        </>
      )}
    </div>
  )
}
