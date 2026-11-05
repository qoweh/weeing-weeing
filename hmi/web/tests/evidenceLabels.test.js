import test from 'node:test'
import assert from 'node:assert/strict'
import { evidenceLabel, referenceLabels } from '../src/components/evidenceLabels.js'

test('shows actual PDF page instead of chunk number or source hash', () => {
  const evidence = { evidence_id: `MAN:2.0:0010:${'a'.repeat(64)}`, title: '설비 매뉴얼', doc_id: 'MAN', doc_version: '2.0', page: 8, section: '고온 점검' }
  assert.equal(evidenceLabel(evidence), '설비 매뉴얼 · v2.0 · PDF 8쪽 · 고온 점검')
  assert.deepEqual(referenceLabels([evidence.evidence_id], [evidence]), [evidenceLabel(evidence)])
})

test('legacy sources never infer a page from the chunk sequence', () => {
  const evidence = { evidence_id: 'MAN:2.0:0010:hash', citation: '매뉴얼 05절', doc_id: 'MAN', doc_version: '2.0' }
  assert.equal(evidenceLabel(evidence), '매뉴얼 05절')
  assert.deepEqual(referenceLabels(['missing'], [evidence]), ['출처 정보 확인 필요'])
})

test('report references preserve the synthetic label and never fabricate a PDF page', () => {
  const evidence = { title: '정비 보고서', doc_version: '2', citation: '보고서 (가상 사례)', page: null }
  assert.equal(evidenceLabel(evidence), '정비 보고서 · v2 · 가상 사례')
})

test('multiple chunks on the same PDF page can share one readable reference', () => {
  const sources = ['a', 'b'].map((evidence_id) => ({ evidence_id, title: '매뉴얼', page: 8 }))
  assert.deepEqual(referenceLabels(['a', 'b'], sources), ['매뉴얼 · PDF 8쪽'])
})
