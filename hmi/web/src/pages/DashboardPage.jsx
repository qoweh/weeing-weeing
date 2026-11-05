import { useEffect, useRef, useState } from 'react'
import { demoNormalValues, runDashboardSimulation } from './incidentSimulation'
import './dashboard-demo.scss'

const sensorLabels = [
  ['motor_housing_temp_c', '모터 외함 온도', '℃'],
  ['rpm', '모터 회전 속도', 'rpm'],
  ['dc_input_current_a', 'DC 입력 전류', 'A'],
  ['dc_bus_voltage_v', 'DC 버스 전압', 'V'],
  ['de_vibration_rms_g', '구동측 진동', 'g'],
  ['nde_vibration_rms_g', '반구동측 진동', 'g'],
]

export default function DashboardPage({ onNavigate }) {
  const [connection, setConnection] = useState('stopped')
  const [phase, setPhase] = useState('normal')
  const [values, setValues] = useState(demoNormalValues)
  const [incident, setIncident] = useState(null)
  const [error, setError] = useState('')
  const mode = useRef('normal')
  const target = useRef(null)
  const previousStates = useRef(new Map())
  const controller = useRef(null)
  useEffect(() => () => controller.current?.abort(), [])

  async function start() {
    if (controller.current) return
    const run = new AbortController()
    controller.current = run
    mode.current = 'normal'; target.current = null; previousStates.current.clear()
    setConnection('connecting'); setPhase('normal'); setIncident(null); setError('')
    try {
      await runDashboardSimulation({
        signal: run.signal,
        getMode: () => mode.current,
        onConnected: () => setConnection('connected'),
        onFrame: (record, response) => {
          setValues(record)
          const changes = response.incidents || []
          const match = changes.find((item) => item.codes.includes('BTT2-M10') && item.severity === 'Error')
          if (match && !target.current && !['RECOVERED', 'CLOSED'].includes(match.status)) {
            target.current = match.incident_id
            setIncident(match); setPhase('detected')
          }
          const recovered = changes.find((item) => item.incident_id === target.current && item.status === 'RECOVERED')
          if (recovered) { setIncident(recovered); setPhase('recovered') }
          let changed = false
          for (const item of changes) {
            const state = `${item.severity}:${item.status}`
            if (previousStates.current.get(item.incident_id) !== state) changed = true
            previousStates.current.set(item.incident_id, state)
          }
          if (changed) window.dispatchEvent(new Event('weeing:incidents-changed'))
        },
      })
    } catch (failure) {
      if (!run.signal.aborted) setError(failure.message)
    } finally {
      if (controller.current === run) { controller.current = null; setConnection('stopped') }
    }
  }
  function inject() { mode.current = 'error'; target.current = null; setIncident(null); setPhase('waiting') }
  function recover() { mode.current = 'normal'; setPhase(target.current ? 'recovering' : 'normal') }
  const labels = { normal: '정상 운전', waiting: '고온 감지 대기', detected: '고온 오류 감지', recovering: '정상 복구 확인 중', recovered: '정상 회복' }
  return <div className="demo-dashboard">
    <div className="demo-dashboard__heading"><div><span className="demo-dashboard__eyebrow">SIMULATION</span><h1>설비 시뮬레이션</h1><p>가상 센서값으로 이상 감지부터 복구까지 확인합니다.</p></div><span className={`demo-dashboard__badge demo-dashboard__badge--${connection}`}>{connection === 'connected' ? '● 전송 중' : connection === 'connecting' ? '연결 중' : '전송 중지'}</span></div>
    <div className="demo-dashboard__notice">시뮬레이션 데이터는 실제 DB에 저장됩니다. Error 발생 시 AI 분석이 실행되어 API 비용이 발생할 수 있습니다.</div>
    {error && <p className="demo-dashboard__error" role="alert">{error}</p>}
    <div className="demo-dashboard__grid">
      <section className="demo-dashboard__card"><div className="demo-dashboard__card-head"><div><span className="demo-dashboard__eyebrow">BLDC-001</span><h2>센서 전송 제어</h2></div><span className={`demo-dashboard__phase demo-dashboard__phase--${phase}`}>{connection === 'connected' ? labels[phase] : '대기'}</span></div>
        <p>시뮬레이션을 시작하면 1초 간격으로 가상 센서값을 보냅니다. 다른 페이지에서도 전송은 계속됩니다.</p>
        <div className="demo-dashboard__actions"><button type="button" className="demo-dashboard__primary" onClick={start} disabled={connection !== 'stopped'}>시뮬레이션 시작</button><button type="button" onClick={() => controller.current?.abort()} disabled={connection === 'stopped'}>전송 중지</button></div>
        <div className="demo-dashboard__scenario"><div><strong>BTT2-M10 · 모터 외함 고온</strong><p>온도 95℃를 전송합니다. Error 확정까지 약 10초가 필요합니다.</p></div><button type="button" className="demo-dashboard__danger" onClick={inject} disabled={connection !== 'connected' || ['waiting', 'detected', 'recovering'].includes(phase)}>고온 오류 발생</button></div>
        <div className="demo-dashboard__scenario"><div><strong>조치 후 정상값 전송</strong><p>온도를 65℃로 바꿉니다. 정상 상태가 약 10초 유지되면 회복됩니다.</p></div><button type="button" className="demo-dashboard__success" onClick={recover} disabled={connection !== 'connected' || !['waiting', 'detected'].includes(phase)}>조치 완료</button></div>
        {incident && <div className="demo-dashboard__incident"><span>{incident.codes.join(', ')}{incident.incident_number ? ` · ${incident.incident_number}` : ''}</span><button type="button" onClick={() => onNavigate('incident-history')}>이상현황 보기 →</button></div>}
      </section>
      <section className="demo-dashboard__card"><div className="demo-dashboard__card-head"><div><span className="demo-dashboard__eyebrow">LIVE TEST DATA</span><h2>현재 전송값</h2></div><span>가상 데이터</span></div><div className="demo-dashboard__sensors">{sensorLabels.map(([key, label, unit]) => <div key={key}><span>{label}</span><strong>{connection === 'connected' ? values[key] : '—'} <small>{unit}</small></strong></div>)}</div><p className="demo-dashboard__hint">입구·출구 센서: 물체 없음 · 운전 조건은 시연용 가정입니다.</p></section>
    </div>
  </div>
}
