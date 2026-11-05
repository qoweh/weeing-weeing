import AnalysisText from './AnalysisText'
import EvidenceReferences from './EvidenceReferences'

export default function AnalysisActions({ analysis, approval = false, showSources = true }) {
  const actions = approval ? analysis?.actions_requiring_approval : analysis?.recommended_actions
  const citations = (approval ? analysis?.approval_citations : analysis?.action_citations) || []
  if (!actions?.length) return null
  return <ol>{actions.map((text, index) => <li key={index}>
    <AnalysisText text={text} />
    {showSources && <EvidenceReferences ids={citations.find((item) => item.action_index === index)?.evidence_ids || []} evidence={analysis.evidence || []} />}
  </li>)}</ol>
}
