import { analysisProgress } from './analysisProgress'
import './analysis-progress.scss'

export default function AnalysisProgress({ result }) {
  const progress = analysisProgress(result)
  if (!progress) return null
  return <section className={`analysis-progress analysis-progress--${progress.tone}`} aria-label="AI 분석 진행 상태">
    <div className="analysis-progress__headline" role="status" aria-live="polite">
      {progress.tone === 'running' && <span className="analysis-progress__spinner" aria-hidden="true" />}
      <div><strong>{progress.title}</strong><p>{progress.description}</p></div>
    </div>
    <ol className="analysis-progress__steps">{progress.steps.map((step) => <li key={step.role} data-status={step.status} data-verdict={step.verdict}>
      <span className="analysis-progress__marker" aria-hidden="true">{step.status === 'FAILED' || ['CAUTION', 'REVISE', 'INSUFFICIENT_EVIDENCE'].includes(step.verdict) ? '!' : step.status === 'COMPLETED' ? '✓' : step.status === 'SKIPPED' ? '–' : '●'}</span>
      <span><strong>{step.label}</strong><small>{step.detail}</small></span>
    </li>)}</ol>
  </section>
}
