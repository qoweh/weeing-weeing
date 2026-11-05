import { useEffect, useRef, useState } from 'react'
import { getIncidentAnalysis, retryIncidentAnalysis } from '../api/client'
import { newRequestId } from '../api/requestId'
import { pollAnalysis } from './pollAnalysis'

export default function AnalysisRetry({ incidentId, result, user, onResult, onSessionExpired }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const running = useRef(null)
  const request = useRef(null)
  useEffect(() => () => running.current?.abort(), [])

  async function retry() {
    if (running.current) return
    const controller = new AbortController()
    running.current = controller
    setBusy(true); setError('')
    const jobId = result.job.job_id
    try {
      // 응답을 받지 못한 같은 요청은 같은 UUID로 보내 추가 유료 실행을 막는다.
      if (request.current?.job_id !== jobId) request.current = { job_id: jobId, request_id: newRequestId() }
      const job = await retryIncidentAnalysis(incidentId, request.current, controller.signal)
      if (controller.signal.aborted) return
      request.current = null
      onResult({ job, analysis: null, stages: [], retry_mode: null })
      await pollAnalysis(incidentId, getIncidentAnalysis, controller.signal, onResult)
    } catch (failure) {
      if (controller.signal.aborted) return
      if (failure.status === 401) { onSessionExpired?.(); return }
      setError(`${failure.message} 결과를 새로고침하면 서버의 진행 상태를 확인할 수 있습니다.`)
    } finally {
      if (running.current === controller) {
        running.current = null
        if (!controller.signal.aborted) setBusy(false)
      }
    }
  }

  if (!onResult || !['관제 담당자', '보전 팀장', '현장 점검자'].includes(user?.role)) return null
  const canRetry = result?.job?.status === 'FAILED' && Boolean(result.retry_mode)
  if (!busy && !error && !canRetry) return null
  return <div className="analysis-retry">
    {(canRetry || busy) && <button type="button" disabled={busy} onClick={retry}>{busy ? '재시도 진행 중…' : result.retry_mode === 'resume' ? '실패 단계부터 재시도' : '분석 다시 시도'}</button>}
    {(canRetry || busy) && <p role="status">{busy ? '분석 진행 상태를 확인하고 있습니다.' : result.retry_mode === 'resume' ? '완료된 단계는 재사용하고 실패한 단계와 이후 단계만 다시 실행합니다.' : '이 작업에는 재개 기록이 없어 처음부터 다시 실행합니다.'}</p>}
    {error && <p className="incident-test__error" role="alert">{error}</p>}
  </div>
}
