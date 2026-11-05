const ROLES = [
  ['documents', '문서 조사'],
  ['reports', '정비이력 조사'],
  ['synthesis', '통합 분석'],
  ['verification', '근거 검증'],
]

const LABELS = { PENDING: '대기', RUNNING: '진행 중', COMPLETED: '완료', FAILED: '실패', SKIPPED: '생략' }

export function analysisProgress(result) {
  const state = result?.job?.status
  const stages = result?.stages || []
  if (!state || !stages.length) return null
  const latest = Object.fromEntries(ROLES.map(([role]) => [role, stages.filter((run) => run.role === role).sort((a, b) => b.attempt - a.attempt)[0]]))
  const steps = ROLES.map(([role, label]) => {
    const run = latest[role]
    let detail = LABELS[run?.status] || '대기'
    if (role === 'synthesis' && run?.status === 'RUNNING' && run.summary === '센서 이력 확인 중') detail = '센서 이력 확인 중'
    if (run?.status === 'COMPLETED' && role === 'verification') {
      detail = { PASS: '검증 통과', REVISE: '수정 필요', INSUFFICIENT_EVIDENCE: '근거 부족' }[run.verification?.verdict] || detail
    }
    if (run?.attempt > 1 && ['synthesis', 'verification'].includes(role)) detail = `2차 · ${detail}`
    if (run?.reused_from_job_id && run.status === 'COMPLETED') detail += ' · 재사용'
    return { role, label, status: run?.status || 'PENDING', verdict: run?.verification?.verdict, detail }
  })
  const failed = ROLES.map(([role]) => latest[role]).find((run) => run?.status === 'FAILED')
  const running = ROLES.filter(([role]) => latest[role]?.status === 'RUNNING')
  const verification = latest.verification
  let title
  let description
  let tone = 'neutral'
  if (result.error) {
    title = '분석 상태 확인 실패'
    description = '아래는 마지막으로 확인한 상태입니다. 새로고침해 다시 확인하세요.'
    tone = 'warning'
  } else if (state === 'FAILED') {
    const name = ROLES.find(([role]) => role === failed?.role)?.[1]
    title = name ? `${failed.attempt > 1 ? '2차 ' : ''}${name} 실패` : '분석 실패'
    if (failed?.summary?.startsWith('센서 이력 조회에 실패')) title = '센서 이력 조회 실패'
    description = '분석을 완료하지 못했습니다. 아래 단계별 결과에서 상세 상태를 확인할 수 있습니다.'
    tone = 'failed'
  } else if (state === 'COMPLETED') {
    if (result.analysis?.status === 'VERIFICATION_FAILED') {
      title = '분석 종료 · 검증 미통과'
      description = '수정 후에도 확인할 오류가 남았습니다. 초안과 근거 검증 지적을 함께 확인하세요.'
      tone = 'warning'
    } else if (result.analysis?.status === 'INSUFFICIENT_EVIDENCE') {
      title = '분석 완료 · 근거 부족'
      description = '충분한 근거가 없어 추가 확인이 필요합니다.'
      tone = 'warning'
    } else if (verification?.status === 'COMPLETED' && verification.verification?.verdict === 'PASS') {
      title = '분석 완료 · 검증 통과'
      description = '통합 분석과 근거 검증이 완료되었습니다.'
      tone = 'completed'
    } else if (verification?.status === 'SKIPPED' && verification.summary === '환경 설정에서 검증을 끔') {
      title = '분석 완료 · 근거 검증 생략'
      description = '검증 기능이 꺼져 있어 통합 분석 결과를 표시합니다.'
      tone = 'completed'
    } else {
      title = '분석 완료'
      description = '아래에서 분석 결과와 단계별 상태를 확인하세요.'
      tone = 'completed'
    }
  } else if (running.length) {
    const names = running.map(([role, label]) => {
      const run = latest[role]
      if (role === 'synthesis' && run.summary === '센서 이력 확인 중') return '센서 이력 확인'
      if (role === 'synthesis' && run.attempt > 1) return '분석 수정'
      if (role === 'verification' && run.attempt > 1) return '2차 근거 검증'
      return label
    })
    title = `${names.join(' · ')} 중`
    description = '단계가 완료되면 진행 상태와 결과가 자동으로 갱신됩니다.'
    tone = 'running'
  } else if (verification?.verification?.verdict === 'REVISE' && verification.attempt === 1) {
    title = '분석 수정 준비 중'
    description = '1차 검증에서 발견한 내용을 통합 분석에 반영합니다.'
    tone = 'running'
  } else if (state === 'RUNNING') {
    title = '분석 진행 중'
    description = '다음 단계의 진행 상태를 확인하고 있습니다.'
    tone = 'running'
  } else {
    title = '분석 대기 중'
    description = '분석 작업이 시작되면 진행 상태가 표시됩니다.'
  }
  return { title, description, tone, steps }
}
