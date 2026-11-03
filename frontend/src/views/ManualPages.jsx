import { useEffect, useRef, useState } from 'react'
import { deleteDocument, listDocuments, uploadDocument } from '../api/client'
import DeleteDocumentDialog from '../components/ui/DeleteDocumentDialog'
import DocumentPdfModal from '../components/ui/DocumentPdfModal'
import Button from '../components/ui/Button'
import PageTitle from '../components/ui/PageTitle'
import { documentVersionFromFilename } from '../components/ui/documentVersion'
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
function toManualRow(r) {
  return {
    ...r,
    id: `${r.doc_id}:${r.doc_version}`,
    name: r.title || r.doc_id,
    asset: r.asset_id,
    version: `v${r.doc_version}`,
    date: r.uploaded_at || r.indexed_at,
    status: labels[r.status] || r.status,
  }
}
export function ManualPage({ user, onNavigate, onSessionExpired, onBusyChange }) {
  const canManage = user?.role === '관제 담당자'
  const [deleting, setDeleting] = useState(null)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [rows, setRows] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState({ period: '', docType: '' })
  const [selected, setSelected] = useState(null)
  const [search, setSearch] = useState({ term: '', reload: -1, items: [], error: '' })
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    listDocuments()
      .then((data) => {
        if (active) setRows(data.map(toManualRow))
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
  const term = query.trim()
  const searchPending = Boolean(term) && (search.term !== term || search.reload !== reload)
  useEffect(() => {
    if (!term) return
    let cancelled = false
    // 입력이 멈춘 뒤 300ms 후에만 서버 검색을 요청한다.
    const timer = setTimeout(() => {
      listDocuments(term)
        .then((data) => {
          if (!cancelled) setSearch({ term, reload, items: data.map(toManualRow), error: '' })
        })
        .catch((failure) => {
          if (cancelled) return
          if (failure.status === 401) onSessionExpired()
          setSearch({ term, reload, items: [], error: failure.message })
        })
    }, 300)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [term, reload, onSessionExpired])
  async function removeDocument() {
    if (!deleting || deleteBusy || !canManage) return
    const target = deleting
    setDeleteBusy(true)
    onBusyChange?.(true)
    setError('')
    setNotice('')
    try {
      await deleteDocument(target)
      setRows((items) => items.filter((item) => item.id !== target.id))
      setSelected(null)
      setNotice(`‘${target.name}’ 문서와 검색 자료를 삭제했습니다.`)
      setReload((n) => n + 1)
    } catch (e) {
      if (e.status === 401) onSessionExpired()
      setError(e.message)
    } finally {
      setDeleting(null)
      setDeleteBusy(false)
      onBusyChange?.(false)
    }
  }
  return (
    <div className="library-page" aria-label="매뉴얼 · 문서 관리">
      <PageTitle>문서내역</PageTitle>
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
          문서 등록
        </Button>
      </Filters>
      {notice && <p role="status">{notice}</p>}
      {loading || searchPending ? (
        <p role="status">{loading ? '문서를 불러오는 중입니다.' : '문서를 검색하고 있습니다.'}</p>
      ) : error || (term && search.error) ? (
        <p className="workspace-error" role="alert">
          {error || search.error}{' '}
          <Button onClick={() => setReload((n) => n + 1)}>다시 시도</Button>
        </p>
      ) : (
        <LibraryTable
          title="전체"
          rows={filterRows(term ? search.items : rows, '', filters)}
          highlight={term}
          onOpen={setSelected}
        />
      )}
      {deleting && (
        <DeleteDocumentDialog
          doc={deleting}
          busy={deleteBusy}
          onCancel={() => setDeleting(null)}
          onConfirm={removeDocument}
        />
      )}
      {selected && (
        <DocumentPdfModal
          key={selected.id}
          doc={selected}
          onClose={() => setSelected(null)}
          onSessionExpired={onSessionExpired}
          onDelete={canManage ? () => setDeleting(selected) : undefined}
        />
      )}
    </div>
  )
}
export function ManualUploadPage({
  onNavigate,
  onSessionExpired,
  onBusyChange,
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [version, setVersion] = useState('1.0')
  const dragDepth = useRef(0)
  const formRef = useRef(null)

  async function uploadFormData(form, data, file) {
    if (busy) return
    setError('')
    if (
      !file?.size ||
      !file.name.toLowerCase().endsWith('.pdf') ||
      file.size > 200 * 1024 * 1024
    ) {
      setError('20 MB 이하의 비어 있지 않은 PDF 파일을 선택하세요.')
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
      await uploadDocument(data)
      onNavigate('manuals')
    } catch (e) {
      setError(e.message)
      if (e.status === 401) onSessionExpired()
    } finally {
      setBusy(false)
      onBusyChange(false)
    }
  }

  async function submit(e) {
    e.preventDefault()
    const form = e.currentTarget
    const data = new FormData(form)
    await uploadFormData(form, data, data.get('file'))
  }

  function handleDrop(event) {
    if (!event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    if (busy) return
    setDragging(false)
    dragDepth.current = 0
    const file = event.dataTransfer.files[0]
    const form = formRef.current
    if (!file || !form) return
    form.elements.namedItem('file').files = event.dataTransfer.files
    const droppedVersion = documentVersionFromFilename(file.name)
    setVersion(droppedVersion)
    const id = form.elements.namedItem('doc_id')
    if (!id.value.trim()) id.value = file.name.replace(/\.pdf$/i, '').trim().replace(/\s+/g, '-')
    setError('')
  }

  return (
    <div
      className={`manual-upload-page ${dragging ? 'manual-upload-page--dragging' : ''}`}
      onDragEnter={(event) => {
        if (!event.dataTransfer.types.includes('Files') || busy) return
        event.preventDefault()
        dragDepth.current += 1
        setDragging(true)
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes('Files')) event.preventDefault()
      }}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget)) return
        event.preventDefault()
        dragDepth.current = 0
        setDragging(false)
      }}
      onDrop={handleDrop}
    >
      {dragging && <div className="library-drop-overlay">PDF 파일을 놓아 선택하세요</div>}
      <form ref={formRef} id="manual-upload-form" onSubmit={submit} className="manual-upload-card">
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
                onChange={(event) =>
                  setVersion(
                    documentVersionFromFilename(
                      event.target.files?.[0]?.name ?? '',
                    ),
                  )
                }
              />
              <span className="library-footnote">PDF 파일 · 최대 20 MB</span>
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
              <input
                name="doc_version"
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                required
              />
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
          문서 등록 실행 {busy && <span className="manual-upload-spinner" aria-label="등록 중" />}
        </Button>
      </div>
    </div>
  )
}
