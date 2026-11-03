import type { Analysis } from './ReportForm'
import './ReportForm.css'

export default function ReportAnalysisSection({
  analysis: linkedAnalysis,
}: {
  analysis: Analysis | null
}) {
  const analysisReady = linkedAnalysis?.status === 'OK'
  const analysisMessage = !linkedAnalysis
    ? 'AI 초안이 아직 연결되지 않았습니다.'
    : linkedAnalysis.status === 'OK'
      ? '제시된 원인 후보 없음'
      : linkedAnalysis.status === 'INSUFFICIENT_EVIDENCE'
        ? '근거가 부족해 AI 초안 작성을 중단했습니다.'
        : 'AI 분석에 실패했습니다. 담당자 확인이 필요합니다.'
  return (
    <section className="report-section">
      <h3 className="report-section-title">
        <span>03</span>AI 분석 및 대응 권고
      </h3>
      <div className="report-table">
        <div className="report-cell report-cell--wide">
          <strong>추정 원인 및 근거</strong>
          <span>
            {analysisReady && linkedAnalysis.suspected_causes?.length
              ? linkedAnalysis.suspected_causes.map((item, index) => (
                  <span className="report-analysis-item" key={index}>
                    {item.cause} · {item.basis} · 근거 ID:{' '}
                    {item.evidence_ids?.join(', ')}
                  </span>
                ))
              : analysisMessage}
          </span>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>권고 점검 절차</strong>
          <span>
            {analysisReady && linkedAnalysis.recommended_checks?.length
              ? linkedAnalysis.recommended_checks.join(' · ')
              : '제시된 점검 절차 없음'}
            {analysisReady &&
              (linkedAnalysis.recommended_actions?.length ?? 0) > 0 &&
              ` · 권고 조치: ${linkedAnalysis.recommended_actions?.join(' · ')}`}
            {analysisReady &&
              (linkedAnalysis.actions_requiring_approval?.length ?? 0) > 0 &&
              ` · 승인 필요: ${linkedAnalysis.actions_requiring_approval?.join(' · ')}`}
          </span>
        </div>
        <div className="report-cell report-cell--wide">
          <strong>참조 매뉴얼·이력</strong>
          <span>
            {analysisReady && linkedAnalysis.evidence?.length
              ? linkedAnalysis.evidence.map((item) => item.citation).join(' · ')
              : '연결된 근거 없음'}
          </span>
        </div>
      </div>
      {linkedAnalysis?.limitations && (
        <p className="report-note">{linkedAnalysis.limitations}</p>
      )}
    </section>
  )
}
