import IncidentCodes from '../../components/ui/IncidentCodeLabel'
import AnalysisStages from './AnalysisStages.jsx'
import AnalysisProgress from './AnalysisProgress.jsx'
import InspectionChecks from './InspectionChecks.jsx'
import CauseCandidates from './CauseCandidates.jsx'
import ReadableText from './ReadableText'
import AnalysisText from './AnalysisText'
import AnalysisActions from './AnalysisActions'
import MaintenanceReferences from './MaintenanceReferences'
import { evidenceLabel } from './evidenceLabels'
import { EvidenceTrace } from './EvidenceReferences'
import { displayIncidentFacts } from './incidentFacts'
import AnalysisRetry from './AnalysisRetry.jsx'

const jobLabels = { PENDING: '분석 대기 중', RUNNING: 'AI가 근거를 검색하고 분석 중', COMPLETED: '분석 완료', FAILED: '분석 실패' }

function Lines({ title, items }) {
  if (!items?.length) return null
  return <div className="incident-result__group incident-result__group--additional"><h4>{title}</h4><ol>{items.map((item, i) => <li key={i}><AnalysisText text={item} /></li>)}</ol></div>
}

export function AnalysisCard({ incident, result, user, onResult, onSessionExpired, onOpenReport, busy, hideIncidentNumber = false }) {
  const analysis = result?.analysis
  const state = result?.job?.status
  const latestVerification = (result?.stages || []).filter((stage) => stage.role === 'verification').sort((a, b) => b.attempt - a.attempt)[0]?.verification
  return <article className="incident-result">
    <aside className="incident-result__summary" aria-label="분석 요약">
    <div className="incident-result__heading"><div><IncidentCodes codes={incident.codes} />{!hideIncidentNumber && <p>{incident.incident_number || '사건번호는 사건현황에서 확인할 수 있습니다.'}</p>}</div><span>{jobLabels[state] || (result ? '분석 작업 없음' : '분석 작업 확인 중')}</span></div>
    <AnalysisProgress result={result} />
    {result?.error && <p className="incident-test__error" role="alert">{result.error}</p>}
    {state === 'FAILED' && <p className="incident-test__error">분석에 실패했습니다. {result.job?.error_code && `오류: ${result.job.error_code}`}</p>}
    </aside>
    <div className="incident-result__detail">
    {state === 'COMPLETED' && analysis && <>
      {analysis.status !== 'OK' && <p className="incident-result__status">{analysis.status === 'VERIFICATION_FAILED' ? '검증 미통과 · 분석 초안 — 담당자 확인 필요' : analysis.status === 'INSUFFICIENT_EVIDENCE' ? '관련 근거가 부족해 추가 자료가 필요합니다' : 'AI 분석에 실패했습니다'}</p>}
      {analysis.suspected_causes?.length > 0 && <div className="incident-result__group incident-result__group--candidates"><h4>원인·점검 후보</h4><CauseCandidates analysis={analysis} incident={incident} compact showSources={false} /></div>}
      {analysis.recommended_checks?.length > 0 && <div className="incident-result__group incident-result__group--checks"><h4>권고 점검 절차</h4><InspectionChecks analysis={analysis} showSources={false} /></div>}
      {analysis.recommended_actions?.length > 0 && <div className="incident-result__group incident-result__group--actions"><h4>권고 조치</h4><AnalysisActions analysis={analysis} showSources={false} /></div>}
      {analysis.actions_requiring_approval?.length > 0 && <div className="incident-result__group incident-result__group--approval"><h4>승인이 필요한 조치</h4><AnalysisActions analysis={analysis} approval showSources={false} /></div>}
      <Lines title="추가 확인 사항" items={analysis.additional_checks} />
      {analysis.status === 'OK' && latestVerification?.verdict === 'CAUTION' && <div className="incident-result__group incident-result__group--additional incident-result__group--caution" role="note"><h4>검증 주의사항</h4><ol>{latestVerification.issues.map((issue, index) => <li key={index}><AnalysisText text={issue.reason} /><div className="incident-result__caution-check"><strong>확인 사항</strong><AnalysisText text={issue.correction} /></div></li>)}</ol></div>}
      <MaintenanceReferences showSources={false} cases={analysis.reference_cases} evidence={analysis.evidence} onOpenReport={onOpenReport} busy={busy} />
      {analysis.observed_facts && <details className="incident-result__group"><summary>사건·센서 정보</summary><AnalysisText text={displayIncidentFacts(analysis.observed_facts, incident)} /></details>}
      {analysis.limitations && <details className="incident-result__group"><summary>분석 한계 및 데이터 주의사항</summary><AnalysisText text={analysis.limitations} className="incident-result__note" /></details>}
      {analysis.evidence?.length > 0 && <details className="incident-result__group"><summary>참고 자료 원문 · {analysis.evidence.length}건</summary>{analysis.evidence.map((evidence) => <details key={evidence.evidence_id}><summary>{evidenceLabel(evidence)}</summary><ReadableText text={evidence.text} /><EvidenceTrace evidence={evidence} /></details>)}</details>}
    </>}
    {!incident.has_approved_report && <AnalysisRetry incidentId={incident.incident_id} result={result} user={user} onResult={onResult} onSessionExpired={onSessionExpired} />}
    <AnalysisStages stages={result?.stages} incident={incident} />
    </div>
  </article>
}
