import EvidenceReferences from './EvidenceReferences'
import AnalysisText from './AnalysisText'
import { candidateBasis, displayIncidentFacts } from './incidentFacts'

function CandidateDetail({ cause, analysis, incident, showSources }) {
  return <>
    <AnalysisText text={displayIncidentFacts(candidateBasis(cause.basis, analysis.observed_facts), incident)} />
    {showSources && <EvidenceReferences ids={cause.evidence_ids} evidence={analysis.evidence || []} />}
    {cause.observations?.length > 0 && <><p><strong>관련 센서 관측</strong></p><ul>{cause.observations.map((text, index) => <li key={index}><AnalysisText text={text} /></li>)}</ul></>}
    {cause.unconfirmed?.length > 0 && <><p><strong>미확인 사항</strong></p><ul>{cause.unconfirmed.map((text, index) => <li key={index}><AnalysisText text={text} /></li>)}</ul></>}
  </>
}

export default function CauseCandidates({ analysis, incident, compact = false, showSources = true }) {
  if (!analysis?.suspected_causes?.length) return null
  return <ul>{analysis.suspected_causes.map((cause, index) => <li key={index}>
    <div className="incident-result__candidate-heading"><strong>{cause.cause}</strong><span className="incident-result__candidate-status">{cause.likelihood === '미평가' ? '미평가 · 추가 점검 필요' : `가능성 ${cause.likelihood}`}</span></div>
    {compact ? <details className="incident-result__candidate-detail"><summary>{showSources ? '후보 설명·출처·확인 사항' : '후보 설명·확인 사항'}</summary><CandidateDetail cause={cause} analysis={analysis} incident={incident} showSources={showSources} /></details> : <CandidateDetail cause={cause} analysis={analysis} incident={incident} showSources={showSources} />}
  </li>)}</ul>
}
