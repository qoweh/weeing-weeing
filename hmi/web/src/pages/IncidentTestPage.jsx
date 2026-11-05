import { useEffect, useRef, useState } from 'react'
import AnalysisStages from '../components/AnalysisStages.jsx'
import AnalysisProgress from '../components/AnalysisProgress.jsx'
import InspectionChecks from '../components/InspectionChecks.jsx'
import CauseCandidates from '../components/CauseCandidates.jsx'
import ReadableText from '../components/ReadableText'
import AnalysisText from '../components/AnalysisText'
import AnalysisActions from '../components/AnalysisActions'
import MaintenanceReferences from '../components/MaintenanceReferences'
import { evidenceLabel } from '../components/evidenceLabels'
import { EvidenceTrace } from '../components/EvidenceReferences'
import { displayIncidentFacts } from '../components/incidentFacts'
import AnalysisRetry from '../components/AnalysisRetry.jsx'
import { getIncidentAnalysis } from '../api/client'
import { pollAnalysis, simulateIncident } from './incidentSimulation'
import './incident-test.scss'

const fields = [
  ['rpm', '모터 회전 속도', 'rpm', '1015'],
  ['dc_input_current_a', 'DC 입력 전류', 'A', '0.0918'],
  ['dc_bus_voltage_v', 'DC 버스 전압', 'V', '24'],
  ['motor_housing_temp_c', '모터 외함 온도', '℃', '95'],
  ['de_vibration_rms_g', '구동측 진동 RMS', 'g', '0.06'],
  ['de_kurtosis', '구동측 진동 첨도', '', '5'],
  ['nde_vibration_rms_g', '반구동측 진동 RMS', 'g', '0.055'],
  ['nde_kurtosis', '반구동측 진동 첨도', '', '4.5'],
]
const defaults = Object.fromEntries(fields.map(([name, , , value]) => [name, value]))
const jobLabels = { PENDING: '분석 대기 중', RUNNING: 'AI가 근거를 검색하고 분석 중', COMPLETED: '분석 완료', FAILED: '분석 실패' }

function Lines({ title, items }) {
  if (!items?.length) return null
  return <div className="incident-result__group"><h4>{title}</h4><ol>{items.map((item, i) => <li key={i}><AnalysisText text={item} /></li>)}</ol></div>
}

export function AnalysisCard({ incident, result, user, onResult, onSessionExpired, onOpenReport, busy }) {
  const analysis = result?.analysis
  const state = result?.job?.status
  return <article className="incident-result">
    <div className="incident-result__heading"><div><strong>{incident.codes.join(', ')}</strong><p>{incident.incident_number || '사건번호는 이상현황에서 확인할 수 있습니다.'}</p></div><span>{jobLabels[state] || (result ? '분석 작업 없음' : '분석 작업 확인 중')}</span></div>
    <AnalysisProgress result={result} />
    {result?.error && <p className="incident-test__error" role="alert">{result.error}</p>}
    {state === 'FAILED' && <p className="incident-test__error">분석에 실패했습니다. {result.job?.error_code && `오류: ${result.job.error_code}`}</p>}
    {state === 'COMPLETED' && analysis && <>
      <p className="incident-result__status">{analysis.status === 'OK' ? '근거 기반 분석 결과' : analysis.status === 'VERIFICATION_FAILED' ? '검증 미통과 · 분석 초안 — 담당자 확인 필요' : analysis.status === 'INSUFFICIENT_EVIDENCE' ? '관련 근거가 부족해 추가 자료가 필요합니다' : 'AI 분석에 실패했습니다'}</p>
      {analysis.status === 'VERIFICATION_FAILED' && <p className="incident-result__note">수정 후에도 확인할 오류가 남았습니다. 아래 내용은 검증을 통과하지 못한 초안입니다. 자세한 지적은 근거 검증 탭에서 확인하세요.</p>}
      {incident.telemetry_provenance?.origin === 'SIMULATION' && <p className="incident-result__note">시뮬레이션 자료 기준 · 실제 고장 원인 확정에는 현장 확인이 필요합니다.</p>}
      {analysis.suspected_causes?.length > 0 && <div className="incident-result__group"><h4>원인·점검 후보</h4><CauseCandidates analysis={analysis} incident={incident} compact /></div>}
      {analysis.recommended_checks?.length > 0 && <div className="incident-result__group"><h4>권고 점검 절차</h4><InspectionChecks analysis={analysis} /></div>}
      {analysis.recommended_actions?.length > 0 && <div className="incident-result__group"><h4>권고 조치</h4><AnalysisActions analysis={analysis} /></div>}
      {analysis.actions_requiring_approval?.length > 0 && <div className="incident-result__group"><h4>승인이 필요한 조치</h4><AnalysisActions analysis={analysis} approval /></div>}
      <Lines title="추가 확인 사항" items={analysis.additional_checks} />
      <MaintenanceReferences cases={analysis.reference_cases} evidence={analysis.evidence} onOpenReport={onOpenReport} busy={busy} />
      {analysis.observed_facts && <details className="incident-result__group"><summary>사건·센서 정보</summary><AnalysisText text={displayIncidentFacts(analysis.observed_facts, incident)} /></details>}
      {analysis.limitations && <details className="incident-result__group"><summary>분석 한계 및 데이터 주의사항</summary><AnalysisText text={analysis.limitations} className="incident-result__note" /></details>}
      {analysis.evidence?.length > 0 && <details className="incident-result__group"><summary>참고 자료 원문 · {analysis.evidence.length}건</summary>{analysis.evidence.map((evidence) => <details key={evidence.evidence_id}><summary>{evidenceLabel(evidence)}</summary><ReadableText text={evidence.text} /><EvidenceTrace evidence={evidence} /></details>)}</details>}
      <p className="incident-result__note">모델: {analysis.model} · AI의 제안은 담당자가 확인해야 합니다.</p>
    </>}
    {!incident.has_approved_report && <AnalysisRetry incidentId={incident.incident_id} result={result} user={user} onResult={onResult} onSessionExpired={onSessionExpired} />}
    <AnalysisStages stages={result?.stages} incident={incident} />
  </article>
}

export default function IncidentTestPage({ onSessionExpired, user }) {
  const [values, setValues] = useState(defaults)
  const [sensors, setSensors] = useState({ infeed_present: false, outfeed_present: false })
  const [duration, setDuration] = useState(20)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [incidents, setIncidents] = useState([])
  const [results, setResults] = useState({})
  const run = useRef(null)

  useEffect(() => () => run.current?.abort(), [])

  async function submit(event) {
    event.preventDefault()
    if (run.current) return
    const numeric = Object.fromEntries(fields.map(([name]) => [name, values[name].trim() === '' ? null : Number(values[name])]))
    if (fields.some(([name]) => numeric[name] === null && !['dc_input_current_a', 'motor_housing_temp_c'].includes(name)) || Object.values(numeric).some((value) => value !== null && !Number.isFinite(value))) {
      setError('필수 센서값을 올바른 숫자로 입력해 주세요.')
      return
    }
    const seconds = Number(duration)
    if (!Number.isInteger(seconds) || seconds < 1 || seconds > 120) { setError('전송 시간은 1~120초로 입력해 주세요.'); return }
    const controller = new AbortController()
    run.current = controller
    setBusy(true); setError(''); setIncidents([]); setResults({}); setProgress('센서 서버에 연결하고 있습니다.')
    try {
      const errors = await simulateIncident({
        values: { ...numeric, ...sensors }, duration: seconds, signal: controller.signal,
        onProgress: (elapsed, total) => setProgress(`센서 전송 중 · ${elapsed} / ${total}초`),
        onEvents: (changes) => setIncidents((previous) => {
          const merged = new Map(previous.map((item) => [item.incident_id, item]))
          changes.forEach((item) => merged.set(item.incident_id, item))
          return [...merged.values()]
        }),
      })
      if (!errors.length) { setProgress('전송이 끝났지만 Error가 감지되지 않았습니다. 값이나 전송 시간을 조정해 보세요.'); return }
      setProgress(`Error ${errors.length}건 감지 · AI 분석 결과를 확인하고 있습니다.`)
      await Promise.all(errors.map(async (incident) => {
        try {
          await pollAnalysis(incident.incident_id, getIncidentAnalysis, controller.signal, (result) => setResults((previous) => ({ ...previous, [incident.incident_id]: result })))
        } catch (failure) {
          if (failure.name === 'AbortError') return
          if (failure.status === 401) onSessionExpired()
          setResults((previous) => ({ ...previous, [incident.incident_id]: { ...previous[incident.incident_id], error: failure.message } }))
        }
      }))
      if (!controller.signal.aborted) setProgress('분석 결과 확인이 끝났습니다.')
      else setProgress('확인을 중단했습니다. 이미 시작된 서버 분석은 계속될 수 있습니다.')
    } catch (failure) {
      if (failure.name !== 'AbortError') setError(failure.message)
      else setProgress('확인을 중단했습니다. 이미 시작된 서버 분석은 계속될 수 있습니다.')
    } finally {
      if (run.current === controller) { run.current = null; setBusy(false) }
    }
  }

  const errors = incidents.filter((item) => item.severity === 'Error')
  return <div className="incident-test">
    <header><div className="incident-test__eyebrow">TEST WORKSPACE</div><h1>이상 사건 테스트</h1><p>가상 센서값을 보내 이상 탐지와 AI 분석 흐름을 확인합니다.</p></header>
    <div className="incident-test__notice">테스트 데이터가 실제 사건·센서 이력으로 저장되며, Error 감지 시 Claude API 호출 비용이 발생할 수 있습니다. 운전 상태는 시뮬레이션 조건으로 가정합니다.</div>
    <form className="incident-test__panel" onSubmit={submit}>
      <div className="incident-test__title"><div><h2>센서값 입력</h2><p>설비 BLDC-001 · 입력값을 1초마다 반복 전송합니다.</p></div></div>
      <fieldset disabled={busy}>
        <div className="incident-test__fields">{fields.map(([name, label, unit]) => <label key={name}>{label} {unit && <small>({unit})</small>}<input type="number" step="any" required={!['dc_input_current_a', 'motor_housing_temp_c'].includes(name)} value={values[name]} onChange={(event) => setValues({ ...values, [name]: event.target.value })} /></label>)}</div>
        <div className="incident-test__switches">{[['infeed_present', '입구 센서'], ['outfeed_present', '출구 센서']].map(([name, label]) => <label key={name}>{label}<select value={String(sensors[name])} onChange={(event) => setSensors({ ...sensors, [name]: event.target.value === 'true' })}><option value="false">물체 없음</option><option value="true">물체 감지</option></select></label>)}<label>최대 전송 시간 (초)<input type="number" min="1" max="120" required value={duration} onChange={(event) => setDuration(event.target.value)} /></label></div>
        <p className="incident-test__hint">기본값은 외함 온도 95℃ 예시입니다. 탐지에는 지속 시간과 운전 문맥이 적용됩니다. 이 테스트의 간단한 운전 가정에서는 회전 속도·전류·진동 등 일부 항목이 문맥 부족으로 판정되지 않을 수 있습니다.</p>
        <button className="incident-test__submit" type="submit">이상값 전송 및 분석</button>
      </fieldset>
      {busy && <button className="incident-test__stop" type="button" onClick={() => run.current?.abort()}>전송·결과 확인 중단</button>}
    </form>
    <section className="incident-test__panel" aria-live="polite"><h2>탐지 및 분석 결과</h2>
      {progress && <p className="incident-test__progress" role="status">{progress}</p>}
      {error && <p className="incident-test__error" role="alert">{error}</p>}
      {incidents.length > 0 && <div className="incident-test__events"><h3>감지된 사건</h3>{incidents.map((item) => <p key={item.incident_id}><strong>{item.severity}</strong> · {item.codes.join(', ')} · {item.status}</p>)}</div>}
      {errors.map((incident) => <AnalysisCard key={incident.incident_id} incident={incident} result={results[incident.incident_id]} user={user} onSessionExpired={onSessionExpired} onResult={(next) => setResults((previous) => ({ ...previous, [incident.incident_id]: next }))} />)}
      {!progress && !error && <p className="incident-test__empty">센서값을 전송하면 이곳에 탐지된 사건과 AI 분석 결과가 표시됩니다.</p>}
    </section>
  </div>
}
