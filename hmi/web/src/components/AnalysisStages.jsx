import { useId, useState } from 'react'
import './analysis-stages.scss'
import EvidenceReferences, { EvidenceTrace } from './EvidenceReferences'
import { evidenceLabel } from './evidenceLabels'
import ReadableText from './ReadableText'
import AnalysisText from './AnalysisText'
import AnalysisActions from './AnalysisActions'
import { formatReadableTime } from './readableTime'
import { displayIncidentFacts } from './incidentFacts'
import InspectionChecks from './InspectionChecks'
import CauseCandidates from './CauseCandidates'
import MaintenanceReferences from './MaintenanceReferences'

const roles = [['documents', '문서 근거'], ['reports', '정비이력 근거'], ['synthesis', '통합 근거'], ['verification', '근거 검증']]
const statuses = { PENDING: '대기', RUNNING: '진행 중', COMPLETED: '완료', FAILED: '실패', SKIPPED: '생략' }
const verdicts = { PASS: '검증 통과', REVISE: '수정 필요', INSUFFICIENT_EVIDENCE: '필수 근거 부족' }

function Sources({ run }) {
  const selected = new Set(run.analysis?.evidence?.map((item) => item.evidence_id) || [])
  return <div className="analysis-stages__sources"><h5>확보한 근거 원문 · {run.evidence.length}건</h5>
    {run.evidence.map((item) => <details key={item.evidence_id}><summary>{evidenceLabel(item)}{run.role === 'synthesis' && <span>{selected.has(item.evidence_id) ? '분석에서 인용' : '전달된 참고 근거'}</span>}</summary>
      <p className="analysis-stages__source-id">문서 ID: {item.doc_id} · 버전: {item.doc_version}{item.section && ` · ${item.section}`}</p>
      <EvidenceTrace evidence={item} /><ReadableText text={item.text} className="analysis-stages__original" />
      {item.report_timing?.map((timing) => <p className="analysis-stages__note" key={timing.action_index}>서버 시간 비교 · 조치 {timing.action_index + 1}: {formatReadableTime(timing.action_at)} / 현재 사건 최초 감지: {formatReadableTime(timing.incident_at)} · {timing.offset_seconds === 0 ? '동일 시각' : `사건 ${timing.offset_seconds < 0 ? '이전' : '이후'} ${Math.abs(timing.offset_seconds).toFixed(3)}초`}</p>)}
    </details>)}
    {!run.evidence.length && <p>{['PENDING', 'RUNNING'].includes(run.status) ? '조사가 끝나면 확보한 근거가 표시됩니다.' : '이 단계에 확보된 근거가 없습니다.'}</p>}
  </div>
}

function SensorWindows({ windows = {} }) {
  const origins = { SIMULATION: '시뮬레이션', REPLAY: '기록 재생', MEASURED: '측정값 선언', UNKNOWN: '출처 미확인' }
  return Object.values(windows).map((window) => <details className="analysis-stages__sensor" key={window.window_id}>
    <summary>{window.purpose === 'baseline' ? '기본 조회' : '추가 조회'} · 센서 관측 범위 · {window.sample_count}개 표본</summary>
    <p>요청: {formatReadableTime(window.start)} ~ {formatReadableTime(window.end)}</p>
    <p>반환 표본: {window.first_sample ? formatReadableTime(window.first_sample) : '없음'} ~ {window.last_sample ? formatReadableTime(window.last_sample) : '없음'}</p>
    {window.quality && <>
      <p>출처: {Object.entries(window.quality.origins).map(([origin, count]) => `${origins[origin] || origin} ${count}개`).join(', ') || '출처 미확인'} · 송신자 선언 기준</p>
      <p>요청 {window.quality.requested_duration_s.toFixed(1)}초 · 반환 표본 범위 {window.quality.observed_span_s.toFixed(1)}초 · 예상 전송 주기 {window.quality.expected_interval_s == null ? '미확인 또는 혼합' : `${window.quality.expected_interval_s}초`}</p>
      {window.quality.unobserved_intervals.map((gap, i) => <p key={i}>미관측·미반환: {formatReadableTime(gap.start)} ~ {formatReadableTime(gap.end)} ({gap.duration_s.toFixed(3)}초)</p>)}
    </>}
    <p>반환 표본 사이 최대 간격: {window.max_gap_seconds == null ? '계산할 표본 부족' : `${window.max_gap_seconds.toFixed(3)}초`}</p>
    <p className="analysis-stages__note">관측 공백은 정상으로 채우지 않습니다. 시뮬레이션과 출처 미확인 데이터로 실제 장비 원인을 확정하지 않습니다.</p>
  </details>)
}

export default function AnalysisStages({ stages = [], incident = null }) {
  const [active, setActive] = useState('documents')
  const id = useId()
  if (!stages.length) return null
  const runs = stages.filter((run) => run.role === active).sort((a, b) => a.attempt - b.attempt)
  return <details className="analysis-stages" aria-label="단계별 분석 근거">
    <summary className="analysis-stages__toggle"><strong>분석 과정 및 근거 보기</strong></summary>
    <div className="analysis-stages__tabs" role="tablist" aria-label="분석 단계">{roles.map(([role, label]) => {
      const latest = stages.filter((run) => run.role === role).at(-1)
      return <button type="button" role="tab" key={role} id={`${id}-stage-${role}`} aria-controls={`${id}-panel`} aria-selected={active === role} onClick={() => setActive(role)}>{label}<small>{statuses[latest?.status] || '대기'}</small></button>
    })}</div>
    <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-stage-${active}`}>
      {!runs.length && <p>이 단계는 아직 실행되지 않았습니다.</p>}
      {runs.map((run) => <section className="analysis-stages__run" key={`${run.role}-${run.attempt}`}>
        <div className="analysis-stages__run-heading"><strong>{run.attempt === 2 ? '수정 후 · 2차' : '1차'} {roles.find(([role]) => role === run.role)?.[1]}</strong><span data-status={run.status}>{statuses[run.status]}</span></div>
        {!run.verification && <AnalysisText text={run.summary || (run.status === 'RUNNING' ? '처리 중입니다.' : '실행을 기다리고 있습니다.')} />}
        {run.reused_from_job_id && <p className="analysis-stages__note">이전 실행의 완료 결과를 재사용했습니다. 이 단계의 추가 모델 호출은 없습니다.</p>}
        {run.error_code && <p role="alert" className="analysis-stages__error">오류: {run.error_code}</p>}
        {run.research && <><h5>조사 결과</h5>{run.research.findings.length ? <ul>{run.research.findings.map((finding, index) => <li key={index}><AnalysisText text={finding.statement} /></li>)}</ul> : !run.research.reference_cases?.length && <p>관련 근거를 찾지 못했습니다.</p>}{run.research.limitations.map((text, index) => <AnalysisText key={index} text={text} className="analysis-stages__note" />)}</>}
        {run.research && <MaintenanceReferences cases={run.research.reference_cases} evidence={run.evidence} showSources={false} />}
        {run.analysis && <div className="analysis-stages__draft"><h5>통합 분석 초안</h5><p className="analysis-stages__note">검증 전 또는 수정 단계의 결과입니다. 최종 상태는 상단 분석 결과에서 확인하세요.</p>
          {run.analysis.observed_facts && <><h5>공통 사건·센서 정보</h5><AnalysisText text={displayIncidentFacts(run.analysis.observed_facts, incident)} /></>}
          {run.analysis.suspected_causes.length > 0 && <><h5>원인·점검 후보</h5><CauseCandidates analysis={run.analysis} incident={incident} showSources={false} /></>}
          <h5>점검 순서</h5><InspectionChecks analysis={run.analysis} showSources={false} />
          {run.analysis.recommended_actions?.length > 0 && <><h5>권고 조치</h5><AnalysisActions analysis={run.analysis} showSources={false} /></>}
          {run.analysis.actions_requiring_approval?.length > 0 && <><h5>승인이 필요한 조치</h5><AnalysisActions analysis={run.analysis} approval showSources={false} /></>}
          {run.analysis.additional_checks?.length > 0 && <><h5>추가 확인 사항</h5><ul>{run.analysis.additional_checks.map((text, index) => <li key={index}><AnalysisText text={text} /></li>)}</ul></>}
          <MaintenanceReferences cases={run.analysis.reference_cases} evidence={run.evidence} showSources={false} />
          {run.analysis.limitations && <AnalysisText text={run.analysis.limitations} className="analysis-stages__note" />}
        </div>}
        {run.verification && <div className="analysis-stages__verification"><h5>{verdicts[run.verification.verdict]}</h5><AnalysisText text={run.verification.summary} />{run.verification.issues.map((issue, index) => <article key={index}><strong>지적 {index + 1}</strong><dl><dt>검토한 주장</dt><dd><AnalysisText text={issue.claim} /></dd><dt>문제와 근거</dt><dd><AnalysisText text={issue.reason} /></dd><dt>수정 요청</dt><dd><AnalysisText text={issue.correction} /></dd></dl>{issue.evidence_ids.length > 0 && <EvidenceReferences ids={issue.evidence_ids} evidence={run.evidence} />}</article>)}</div>}
        <SensorWindows windows={run.sensor_windows} />
        {run.status !== 'SKIPPED' && <Sources run={run} />}
      </section>)}
    </div>
  </details>
}
