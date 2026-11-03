import { useEffect, useState } from 'react'
import { listReports } from '../api/client'
import PageTitle from '../components/ui/PageTitle'
import './MyPage.scss'

type Report = {
  report_id: string
  report_status: string
  asset_id?: string
  updated_at?: string
}
type User = {
  name: string
  role: string
  employee_no: string
  is_admin: boolean
}

const statusLabels: Record<string, string> = {
  DRAFT: '임시 저장',
  SUBMITTED: '검토 대기',
  REVIEWED: '최종 결재 대기',
  APPROVED: '승인',
  REJECTED: '반려',
}

export default function MyPage({
  user,
  onNavigate,
  onSessionExpired,
  onOpen,
}: {
  user: User
  onNavigate: (page: string) => void
  onSessionExpired: () => void
  onOpen: (id: string) => void
}) {
  const [data, setData] = useState<{ mine: Report[]; review: Report[] } | null>(
    null,
  )
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const canReview = ['보전 팀장', '관제 담당자'].includes(user.role)

  useEffect(() => {
    let active = true
    setData(null)
    setError('')
    Promise.all([
      listReports('mine'),
      ...(canReview ? [listReports('review')] : []),
    ])
      .then(([mine, review = []]) => {
        if (active) setData({ mine, review })
      })
      .catch((failure) => {
        if (!active) return
        if (failure.status === 401) onSessionExpired()
        else setError(failure.message)
      })
    return () => {
      active = false
    }
  }, [canReview, onSessionExpired, retry])

  const recent = (items: Report[]) =>
    [...items]
      .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
      .slice(0, 5)
  const reportList = (items: Report[], empty: string) =>
    items.length ? (
      <ul className="mypage__list">
        {recent(items).map((report) => (
          <li key={report.report_id}>
            <button type="button" onClick={() => onOpen(report.report_id)}>
              <span>
                <strong>{report.report_id}</strong>
                <small>
                  {report.asset_id || '설비 미지정'} ·{' '}
                  {report.updated_at
                    ? new Date(report.updated_at).toLocaleDateString('ko-KR')
                    : '날짜 없음'}
                </small>
              </span>
              <span
                className={`mypage__status mypage__status--${report.report_status.toLowerCase()}`}
              >
                {statusLabels[report.report_status] || report.report_status}
              </span>
            </button>
          </li>
        ))}
      </ul>
    ) : (
      <p className="mypage__empty">{empty}</p>
    )

  return (
    <div className="mypage">
      <PageTitle>마이페이지</PageTitle>
      <section className="mypage__profile" aria-label="내 정보">
        <div className="mypage__avatar" aria-hidden="true">
          {user.name?.slice(0, 1)}
        </div>
        <div className="mypage__identity">
          <div className="mypage__identity-heading">
            <h2>{user.name}</h2>
            <span className="mypage__role">{user.role}</span>
          </div>
          <p className="mypage__meta">
            <span>사번</span>
            <strong>{user.employee_no}</strong>
            {user.is_admin && (
              <span className="mypage__admin">계정 관리자</span>
            )}
          </p>
        </div>
      </section>
      {error ? (
        <p role="alert" className="workspace-error">
          업무를 불러오지 못했습니다: {error}{' '}
          <button
            className="mypage__retry"
            type="button"
            onClick={() => setRetry((n) => n + 1)}
          >
            다시 시도
          </button>
        </p>
      ) : !data ? (
        <p role="status" className="mypage__loading">
          업무 정보를 불러오는 중입니다.
        </p>
      ) : (
        <>
          <div className="mypage__summary" aria-label="업무 요약">
            <div>
              <span className="mypage__summary-label">내 보고서</span>
              <strong>
                {data.mine.length}
                <small>건</small>
              </strong>
            </div>
            <div>
              <span className="mypage__summary-label">임시 저장</span>
              <strong>
                {data.mine.filter((r) => r.report_status === 'DRAFT').length}
                <small>건</small>
              </strong>
            </div>
            <div>
              <span className="mypage__summary-label">반려</span>
              <strong>
                {data.mine.filter((r) => r.report_status === 'REJECTED').length}
                <small>건</small>
              </strong>
            </div>
            {canReview && (
              <div>
                <span className="mypage__summary-label">내 결재 대기</span>
                <strong>
                  {data.review.length}
                  <small>건</small>
                </strong>
              </div>
            )}
          </div>
          <div className="mypage__sections">
            {canReview && (
              <section className="mypage__card">
                <h2>
                  {user.role === '보전 팀장' ? '검토 대기' : '최종 결재 대기'}
                </h2>
                <p>확인이 필요한 보고서입니다.</p>
                {reportList(data.review, '결재 대기 중인 보고서가 없습니다.')}
              </section>
            )}
            <section className="mypage__card">
              <h2>내 보고서</h2>
              <p>최근 작성하거나 수정한 보고서입니다.</p>
              {reportList(data.mine, '작성한 보고서가 없습니다.')}
              <button
                className="mypage__link"
                type="button"
                onClick={() => onNavigate('maintenance')}
              >
                정비이력 전체 보기 <span aria-hidden="true">→</span>
              </button>
            </section>
          </div>
        </>
      )}
      {user.role === '현장 점검자' && (
        <section className="mypage__card mypage__action">
          <div>
            <h2>새 보고서 작성</h2>
            <p>이상현황에서 사건을 선택해 보고서를 작성하세요.</p>
          </div>
          <button
            className="mypage__action-button"
            type="button"
            onClick={() => onNavigate('incidents')}
          >
            이상현황으로 이동 <span aria-hidden="true">→</span>
          </button>
        </section>
      )}
    </div>
  )
}
