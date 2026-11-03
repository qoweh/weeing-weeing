import { useEffect, useState } from 'react'
import {
  listIncidents,
  listReports,
  type Incident,
  type ReportSummary,
} from '../api/client'
import Button from '../components/ui/Button'
import PageTitle from '../components/ui/PageTitle'
import { LibraryTable } from '../components/ui/library'
const labels: Record<string, string> = {
  DRAFT: '임시 저장',
  SUBMITTED: '검토 중',
  REVIEWED: '검토 승인',
  APPROVED: '작성 완료',
  REJECTED: '반려',
}
const activeStatuses = ['OPEN', 'ACKNOWLEDGED']
const historyStatuses = ['RECOVERED', 'CLOSED']
const issueLimit = 3
// 아직 접수되지 않은 사건(OPEN)을 먼저, 같은 상태에서는 최근 발생한 사건을 먼저 둔다.
const urgency = (incident: Incident) => activeStatuses.indexOf(incident.status)
const byUrgency = (a: Incident, b: Incident) =>
  urgency(a) - urgency(b) ||
  String(b.first_detected_at).localeCompare(String(a.first_detected_at))

function toRow(incident: Incident, reports: ReportSummary[]) {
  const report = reports.find((r) => r.incident_id === incident.incident_id)
  return {
    id: report?.report_id || incident.incident_id,
    reportId: report?.report_id,
    incidentId: incident.incident_id,
    name: report?.report_id || '보고서 작성',
    issue: incident.codes.join(', '),
    asset: incident.asset_id,
    date: incident.first_detected_at,
    author: report?.author_name || '—',
    status: report ? labels[report.report_status] : '작성 필요',
    tone: 'warning',
    incident,
  }
}

export default function IncidentsPage({
  onOpen,
  onSessionExpired,
  refreshKey = 0,
}: {
  onOpen: (
    reportId: string | undefined,
    incidentId: string,
    row: ReturnType<typeof toRow>,
  ) => void
  onSessionExpired: () => void
  refreshKey?: number
}) {
  const [issues, setIssues] = useState<ReturnType<typeof toRow>[]>([]),
    [history, setHistory] = useState<ReturnType<typeof toRow>[]>([])
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    Promise.all([listReports('all'), listIncidents()])
      .then(([reports, incidents]) => {
        if (!active) return
        const errors = incidents.filter((i) => i.severity === 'Error')
        setIssues(
          errors
            .filter((i) => activeStatuses.includes(i.status))
            .sort(byUrgency)
            .map((i) => toRow(i, reports)),
        )
        setHistory(
          errors
            .filter((i) => historyStatuses.includes(i.status))
            .map((i) => toRow(i, reports)),
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
  }, [reload, refreshKey, onSessionExpired])
  return (
    <div className="library-page" aria-label="이상 현황">
      <PageTitle>이상현황</PageTitle>
      {loading ? (
        <p role="status">이상 현황을 불러오는 중입니다.</p>
      ) : (
        <>
          {error && (
            <p className="workspace-error" role="alert">
              실제 목록을 불러오지 못했습니다: {error}{' '}
              <Button onClick={() => setReload((n) => n + 1)}>다시 시도</Button>
            </p>
          )}
          <LibraryTable
            report
            compact
            title="오류 이슈"
            emptyTitle="진행 중인 오류 이슈가 없습니다"
            emptyHint="새로운 이상이 감지되면 이곳에 표시됩니다."
            rows={issues.slice(0, issueLimit)}
            totalCount={issues.length}
            initialSort={{ key: 'number', direction: 1 }}
            hint={
              issues.length > issueLimit
                ? `위험도 순 상위 ${issueLimit}건만 표시합니다`
                : '위험도 순으로 표시합니다'
            }
            onOpen={(r: ReturnType<typeof toRow>) =>
              onOpen(r.reportId, r.incidentId, r)
            }
          />
          <LibraryTable
            report
            compact
            title="오류 히스토리"
            emptyTitle={undefined}
            emptyHint={undefined}
            totalCount={undefined}
            rows={history}
            alwaysPaginate
            onOpen={(r: ReturnType<typeof toRow>) =>
              onOpen(r.reportId, r.incidentId, r)
            }
          />
        </>
      )}
    </div>
  )
}
