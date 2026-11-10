import test from 'node:test'
import assert from 'node:assert/strict'
import { canControl, canReviewReports, canRunAnalysis, canWriteReports, reviewStep } from '../src/components/permissions.js'

test('직책별 권한은 백엔드 규칙과 같다', () => {
  const users = ['현장 점검자', '보전 팀장', '관제 담당자', '현장 책임자'].map((role) => ({ role, is_admin: false }))
  assert.deepEqual(users.map((u) => [canWriteReports(u), canReviewReports(u), canControl(u), canRunAnalysis(u)]), [
    [true, false, false, true],
    [true, true, false, true],
    [false, true, true, true],
    [false, false, false, false],
  ])
  assert.equal(reviewStep(users[1], 'SUBMITTED'), 'review')
  assert.equal(reviewStep(users[2], 'SUBMITTED'), null)
})

test('D-36: 계정 관리자는 직책과 관계없이 모든 권한을 가진다', () => {
  const admin = { role: '현장 책임자', is_admin: true }
  assert.ok(canWriteReports(admin) && canReviewReports(admin) && canControl(admin) && canRunAnalysis(admin))
  assert.equal(reviewStep(admin, 'SUBMITTED'), 'review')
  assert.equal(reviewStep(admin, 'REVIEWED'), 'approve')
})
