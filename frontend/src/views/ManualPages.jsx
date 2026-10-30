import { useEffect, useRef, useState } from 'react'
import { listDocuments, uploadDocument } from '../api/client'
import Button from '../components/ui/Button'
import {
  Filters,
  filterRows,
  LibraryTable,
  dateLabel,
} from '../components/ui/library'

const labels = {
  completed: '등록 완료',
  queued: '대기 중',
  processing: '처리 중',
  failed: '등록 실패',
  superseded: '이전 버전',
  deleting: '삭제 중',
  delete_failed: '삭제 실패',
}
export function ManualPage({ onNavigate, onSessionExpired }) {
  const [rows, setRows] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState({ period: '', docType: '' })
  const [selected, setSelected] = useState(null)
  const dialog = useRef(null)
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    listDocuments()
      .then((data) => {
        if (active)
          setRows(
            data.map((r) => ({
              ...r,
              id: `${r.doc_id}:${r.doc_version}`,
              name: r.title || r.doc_id,
              asset: r.asset_id,
              version: `v${r.doc_version}`,
              date: r.uploaded_at || r.indexed_at,
              status: labels[r.status] || r.status,
            })),
          )
      })
      .catch((e) => {
        if (active) {
          setError(e.message)
          if (e.status === 401) onSessionExpired()
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [reload, onSessionExpired])
  return (
    <div className="library-page" aria-label="매뉴얼 · 문서 관리">
      <Filters
        query={query}
        setQuery={setQuery}
        filters={filters}
        setFilters={setFilters}
        onRefresh={() => setReload((n) => n + 1)}
        loading={loading}
      >
        <Button
          variant="primary"
          className="library-upload"
          onClick={() => onNavigate('manual-upload')}
        >
          문서 업로드
        </Button>
      </Filters>
      {loading ? (
        <p role="status">문서를 불러오는 중입니다.</p>
      ) : error ? (
        <p className="workspace-error" role="alert">
          {error}{' '}
          <Button onClick={() => setReload((n) => n + 1)}>다시 시도</Button>
        </p>
      ) : (
        <LibraryTable
          title="전체"
          rows={filterRows(rows, query, filters)}
          onOpen={(r) => {
            setSelected(r)
            dialog.current.showModal()
          }}
        />
      )}
      <p className="library-footnote">PDF 파일 최대 200 MB</p>
      <dialog ref={dialog} className="library-dialog">
        <form method="dialog">
          <Button type="submit" aria-label="문서 정보 닫기">
            닫기
          </Button>
        </form>
        {selected && (
          <>
            <h2>{selected.name}</h2>
            <dl>
              <dt>문서 ID</dt>
              <dd>{selected.doc_id}</dd>
              <dt>적용 설비</dt>
              <dd>{selected.asset || '—'}</dd>
              <dt>버전</dt>
              <dd>{selected.version}</dd>
              <dt>등록일</dt>
              <dd>{dateLabel(selected.date)}</dd>
              <dt>처리 상태</dt>
              <dd>{selected.status}</dd>
            </dl>
            <p>문서 원문 열람은 아직 지원하지 않습니다.</p>
            {selected.error && <p role="alert">{selected.error}</p>}
          </>
        )}
      </dialog>
    </div>
  )
}
const progress = {
  uploading: 'PDF를 업로드하고 있습니다.',
  queued: '처리 순서를 기다리고 있습니다.',
  parsing: '문서를 읽고 있습니다.',
  chunking: '문서를 정리하고 있습니다.',
  loading_model: '검색 준비 중입니다.',
  embedding: '검색 정보를 생성하고 있습니다.',
  storing: '저장 중입니다.',
  completed: '문서 등록이 완료됐습니다.',
}
export function ManualUploadPage({
  onNavigate,
  onSessionExpired,
  onBusyChange,
}) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  async function submit(e) {
    e.preventDefault()
    if (busy) return
    const form = e.currentTarget,
      data = new FormData(form),
      file = data.get('file')
    setError('')
    setMessage('')
    if (
      !file?.size ||
      !file.name.toLowerCase().endsWith('.pdf') ||
      file.size > 200 * 1024 * 1024
    ) {
      setError('200 MB 이하의 비어 있지 않은 PDF 파일을 선택하세요.')
      return
    }
    for (const name of ['doc_id', 'doc_version', 'asset_id']) {
      const value = String(data.get(name)).trim()
      if (!value) {
        setError('필수 항목을 입력하세요.')
        return
      }
      data.set(name, value)
    }
    setBusy(true)
    onBusyChange(true)
    try {
      await uploadDocument(data, (stage) =>
        setMessage(progress[stage] || '처리 중입니다.'),
      )
      setMessage(progress.completed)
      form.reset()
    } catch (e) {
      setMessage('')
      setError(e.message)
      if (e.status === 401) onSessionExpired()
    } finally {
      setBusy(false)
      onBusyChange(false)
    }
  }
  return (
    <div className="manual-upload-page">
      <form id="manual-upload-form" onSubmit={submit} className="manual-upload-card">
        <h1>문서 등록</h1>
        <fieldset disabled={busy}>
          <div className="manual-upload-fields">
            <label className="manual-upload-file">
              PDF 파일
              <input
                type="file"
                name="file"
                accept=".pdf,application/pdf"
                required
              />
              <span className="library-footnote">PDF 파일 · 최대 200 MB</span>
            </label>
            <label>
              문서 ID
              <input
                name="doc_id"
                placeholder="예: BLDC-001-MANUAL (카탈로그 문서 ID는 쓸 수 없음)"
                pattern="[^:\s]+"
                title="공백과 콜론 없이 입력하세요"
                required
              />
            </label>
            <label>
              문서 버전
              <input name="doc_version" defaultValue="1.0" required />
            </label>
            <label>
              문서 종류
              <select name="doc_type" defaultValue="manual">
                <option value="manual">매뉴얼</option>
                <option value="sop">규정·SOP</option>
                <option value="rule">룰베이스</option>
              </select>
            </label>
            <label>
              적용 설비 ID
              <input name="asset_id" defaultValue="BLDC-001" required />
            </label>
          </div>
        </fieldset>
        {message && <p role="status">{message}</p>}
        {error && (
          <p className="workspace-error" role="alert">
            {error}
          </p>
        )}
      </form>
      <div className="manual-upload-back">
        <Button type="button" disabled={busy} onClick={() => onNavigate('manuals')}>
          목록
        </Button>
        <Button type="submit" form="manual-upload-form" variant="primary" disabled={busy}>
          {busy ? '등록 중…' : '문서 등록 실행'}
        </Button>
      </div>
    </div>
  )
}
