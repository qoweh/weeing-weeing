import AnalysisText from './AnalysisText'
import EvidenceReferences from './EvidenceReferences'
import './maintenance-references.scss'

export default function MaintenanceReferences({ cases = [], evidence = [], onOpenReport, busy = false }) {
  if (!cases.length) return null
  return <section className="maintenance-references" aria-label="참고 정비 사례">
    <h4>참고 정비 사례</h4>
    <p className="maintenance-references__note">과거 조치의 참고 사례입니다. 현재 사건의 원인과 적용 가능성은 별도 확인이 필요합니다.</p>
    {cases.map((item, index) => {
      const source = evidence.find((entry) => item.evidence_ids.includes(entry.evidence_id))
      const version = source && /^[1-9]\d*$/.test(source.doc_version) ? Number(source.doc_version) : null
      return <article className="maintenance-references__case" key={item.evidence_ids[0]}>
        <strong>사례 {index + 1}</strong>
        <dl>{[['당시 증상', item.symptom], ['실제 조치', item.action], ['조치 결과', item.outcome], ['현재 사건과 유사점', item.similarity], ['차이점·적용 한계', item.differences]].map(([label, text]) => <div key={label}><dt>{label}</dt><dd><AnalysisText text={text} /></dd></div>)}</dl>
        <EvidenceReferences ids={item.evidence_ids} evidence={evidence} />
        {onOpenReport && source && version && <button type="button" disabled={busy} onClick={() => onOpenReport(source.doc_id, null, version)}>보고서 확인 · {source.doc_id}</button>}
      </article>
    })}
  </section>
}
