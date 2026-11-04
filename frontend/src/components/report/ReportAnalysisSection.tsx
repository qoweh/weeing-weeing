import type { Analysis, ReportIncident } from './ReportForm'
import './ReportForm.css'

function Items({
  items,
  ordered = false,
  empty,
}: {
  items?: string[]
  ordered?: boolean
  empty: string
}) {
  if (!items?.length) return <span>{empty}</span>
  const List = ordered ? 'ol' : 'ul'
  return (
    <List className="report-analysis-list">
      {items.map((text, index) => (
        <li key={index}>{text}</li>
      ))}
    </List>
  )
}

export default function ReportAnalysisSection({
  analysis,
  incident = null,
  showTitle = true,
}: {
  analysis: Analysis | null
  incident?: ReportIncident | null
  showTitle?: boolean
}) {
  const ready = analysis?.status === 'OK'
  const linkedIncident =
    incident?.incident_id === analysis?.incident_id ? incident : null
  const message = !analysis
    ? 'AI 초안이 아직 연결되지 않았습니다.'
    : analysis.status === 'INSUFFICIENT_EVIDENCE'
      ? '근거가 부족해 AI 초안 작성을 중단했습니다.'
      : analysis.status === 'OK'
        ? '제시된 원인 후보 없음'
        : 'AI 분석에 실패했습니다. 담당자 확인이 필요합니다.'
  return (
    <section className="report-section">
      {showTitle && (
        <h3 className="report-section-title">
          <span>03</span>AI 분석 및 대응 권고
        </h3>
      )}
      <div className="report-table">
        <div className="report-cell report-cell--wide">
          <strong>추정 원인 및 근거</strong>
          <div className="report-analysis-content">
            {ready && analysis.suspected_causes?.length ? (
              <ul className="report-analysis-list">
                {analysis.suspected_causes.map((item, index) => (
                  <li key={index}>
                    <strong>{item.cause}</strong>
                    {linkedIncident && (
                      <>
                        <div>
                          설비:{' '}
                          {[linkedIncident.process_id, linkedIncident.asset_id]
                            .filter(Boolean)
                            .join(' / ') || '미확인'}
                        </div>
                        <div>코드: {linkedIncident.codes?.join(', ')}</div>
                      </>
                    )}
                    <div>
                      근거 ID: {item.evidence_ids?.join(', ') || '없음'}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              message
            )}
          </div>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>권고 점검 절차</strong>
          <div className="report-analysis-content">
            <Items
              ordered
              items={ready ? analysis.recommended_checks : []}
              empty="제시된 점검 절차 없음"
            />
          </div>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>권고 조치</strong>
          <div className="report-analysis-content">
            <Items
              items={ready ? analysis.recommended_actions : []}
              empty="제시된 조치 없음"
            />
          </div>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>승인이 필요한 조치</strong>
          <div className="report-analysis-content">
            <Items
              items={ready ? analysis.actions_requiring_approval : []}
              empty="제시된 승인 필요 조치 없음"
            />
          </div>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>참조 매뉴얼·이력</strong>
          <div className="report-analysis-content">
            <Items
              items={
                ready
                  ? analysis.evidence?.map(
                      (item) =>
                        `${item.citation}${item.evidence_id ? ` · 근거 ID: ${item.evidence_id}` : ''}`,
                    )
                  : []
              }
              empty="연결된 근거 없음"
            />
          </div>
        </div>
      </div>
      {analysis?.limitations && (
        <p className="report-note">{analysis.limitations}</p>
      )}
    </section>
  )
}
