import test from 'node:test'
import assert from 'node:assert/strict'
import { analysisProgress } from '../src/incident-hmi/components/analysisProgress.js'

const run = (role, status, extra = {}) => ({ role, status, attempt: 1, ...extra })
const result = (status, stages, analysis = null) => ({ job: { status }, stages, analysis })

test('parallel research and second verification show actual running stages', () => {
  const research = analysisProgress(result('RUNNING', [run('documents', 'RUNNING'), run('reports', 'RUNNING')]))
  assert.equal(research.title, '문서 조사 · 정비이력 조사 중')
  const verify = analysisProgress(result('RUNNING', [run('verification', 'COMPLETED', { verification: { verdict: 'REVISE' } }), run('verification', 'RUNNING', { attempt: 2 })]))
  assert.equal(verify.title, '2차 근거 검증 중')
  assert.equal(verify.steps[3].detail, '2차 · 진행 중')
  assert.equal(analysisProgress(result('RUNNING', [run('synthesis', 'RUNNING', { summary: '센서 이력 확인 중' })])).title, '센서 이력 확인 중')
  assert.equal(analysisProgress(result('FAILED', [run('synthesis', 'FAILED', { summary: '센서 이력 조회에 실패했습니다.' })])).title, '센서 이력 조회 실패')
})

test('revision transition and completed outcomes do not invent a verification pass', () => {
  const revise = run('verification', 'COMPLETED', { verification: { verdict: 'REVISE' } })
  assert.equal(analysisProgress(result('RUNNING', [revise])).title, '분석 수정 준비 중')
  const skip = run('verification', 'SKIPPED', { summary: '환경 설정에서 검증을 끔' })
  assert.equal(analysisProgress(result('COMPLETED', [skip], { status: 'OK' })).title, '분석 완료 · 근거 검증 생략')
  const pass = run('verification', 'COMPLETED', { verification: { verdict: 'PASS' } })
  assert.equal(analysisProgress(result('COMPLETED', [pass], { status: 'OK' })).title, '분석 완료 · 검증 통과')
  assert.equal(analysisProgress(result('COMPLETED', [pass], { status: 'INSUFFICIENT_EVIDENCE' })).title, '분석 완료 · 근거 부족')
  assert.equal(analysisProgress(result('COMPLETED', [revise], { status: 'VERIFICATION_FAILED' })).title, '분석 종료 · 검증 미통과')
})

test('failure names the failed step and resumed work identifies reused results', () => {
  const stages = [run('documents', 'COMPLETED', { reused_from_job_id: 'previous' }), run('verification', 'FAILED', { attempt: 2 })]
  const progress = analysisProgress(result('FAILED', stages))
  assert.equal(progress.title, '2차 근거 검증 실패')
  assert.equal(progress.steps[0].detail, '완료 · 재사용')
  assert.equal(analysisProgress(result('RUNNING', [])), null)
  assert.equal(analysisProgress({ ...result('RUNNING', stages), error: '조회 실패' }).title, '분석 상태 확인 실패')
})


test('completed caution remains visible and is not reported as a pass', () => {
  const caution = run('verification', 'COMPLETED', { verification: { verdict: 'CAUTION' } })
  const progress = analysisProgress(result('COMPLETED', [caution], { status: 'OK' }))
  assert.equal(progress.title, '분석 완료 · 주의사항 확인')
  assert.equal(progress.steps[3].detail, '주의사항 확인')
  assert.equal(progress.tone, 'warning')
})
