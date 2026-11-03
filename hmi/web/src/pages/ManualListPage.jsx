import { useEffect, useId, useRef, useState } from 'react'
import { deleteDocument, listDocuments } from '../api/client'
import './manuals.scss'

const kinds = { manual: '매뉴얼', sop: '규정·SOP', rule: '룰베이스' }
const canManage = (user) => user.role === '관제 담당자'

function DeleteManualDialog({ document, busy, onCancel, onConfirm }) {
  const dialog = useRef(null)
  const cancelButton = useRef(null)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    const element = dialog.current
    const previousFocus = window.document.activeElement
    element.showModal()
    cancelButton.current.focus()
    return () => { element.close(); previousFocus?.focus() }
  }, [])

  return <dialog ref={dialog} className="manual-delete-dialog" aria-labelledby={titleId}
    aria-describedby={descriptionId} onCancel={(event) => { event.preventDefault(); if (!busy) onCancel() }}>
    <span className="manual-delete-dialog__icon" aria-hidden="true">⌫</span>
    <h2 id={titleId}>문서를 삭제할까요?</h2>
    <p className="manual-delete-dialog__title">{document.title}</p>
    <p id={descriptionId}>이 문서의 모든 버전에 해당하는 검색 자료도 함께 삭제됩니다. 삭제가 완료되면 검색과 AI 답변의 근거로 사용되지 않습니다.</p>
    <div className="manual-delete-dialog__actions">
      <button ref={cancelButton} type="button" disabled={busy} onClick={onCancel}>취소</button>
      <button className="manual-delete-button manual-delete-button--solid" type="button" disabled={busy} onClick={onConfirm}>
        {busy ? '삭제 중…' : '삭제하기'}
      </button>
    </div>
  </dialog>
}

export default function ManualListPage({ user, onSessionExpired, onBusyChange, onNavigate }) {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [reload, setReload] = useState(0)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('all')
  const [sortOrder, setSortOrder] = useState('newest')
  const [selected, setSelected] = useState(null)
  const [search, setSearch] = useState({ term: '', reload: -1, items: [], error: '' })
  const term = query.trim()
  const searchPending = Boolean(term) && (search.term !== term || search.reload !== reload)
  const searchError = term && !searchPending ? search.error : ''

  useEffect(() => {
    let cancelled = false
    listDocuments().then((items) => {
      if (!cancelled) setDocuments(items)
    }).catch((failure) => {
      if (cancelled) return
      if (failure.status === 401) onSessionExpired()
      setError(failure.message)
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [reload, onSessionExpired])

  useEffect(() => {
    if (!term) return
    let cancelled = false
    const timer = setTimeout(() => {
      listDocuments(term).then((items) => {
        if (!cancelled) setSearch({ term, reload, items, error: '' })
      }).catch((failure) => {
        if (cancelled) return
        if (failure.status === 401) onSessionExpired()
        setSearch({ term, reload, items: [], error: failure.message })
      })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [term, reload, onSessionExpired])

  function refresh() {
    setLoading(true)
    setError('')
    setReload((value) => value + 1)
  }

  async function removeSelected() {
    if (!selected || busy || !canManage(user)) return
    setBusy(true)
    onBusyChange(true)
    setError('')
    setMessage('')
    try {
      await deleteDocument(selected)
      setDocuments((items) => items.filter((item) => item.doc_id !== selected.doc_id))
      setReload((value) => value + 1)
      setMessage(`‘${selected.title}’ 문서와 검색 자료를 삭제했습니다.`)
    } catch (failure) {
      if (failure.status === 401) onSessionExpired()
      // 실패 상태와 새 버전을 다시 받아 재시도할 수 있게 한다.
      try { setDocuments(await listDocuments()) } catch { /* 원래 삭제 오류를 유지한다. */ }
      setReload((value) => value + 1)
      setError(failure.message)
    } finally {
      setSelected(null)
      setBusy(false)
      onBusyChange(false)
    }
  }

  const visible = (term ? search.items : documents)
    .filter((item) => kind === 'all' || item.doc_type === kind)
    .sort((a, b) => {
      const first = Date.parse(a.uploaded_at)
      const second = Date.parse(b.uploaded_at)
      // 등록일이 없는 이전 문서는 어느 방향에서든 마지막에 표시한다.
      if (!Number.isFinite(first)) return Number.isFinite(second) ? 1 : 0
      if (!Number.isFinite(second)) return -1
      return sortOrder === 'oldest' ? first - second : second - first
    })

  return <section className="manuals-page" aria-label="등록된 문서">
    <div className="manuals-toolbar">
      <p>매뉴얼·규정·룰 문서를 한곳에서 확인하세요. <strong>{documents.length}개 등록</strong></p>
      <div className="manuals-toolbar__actions">
        <button type="button" disabled={loading || busy} onClick={refresh}>목록 새로고침</button>
        {canManage(user) && <button className="primary" type="button" disabled={busy} onClick={() => onNavigate('documents')}>＋ 문서 등록</button>}
      </div>
    </div>
    <div className="panel manuals-filters">
      <label>문서 검색<input type="search" value={query} maxLength={200} onChange={(event) => setQuery(event.target.value)} placeholder="제목, 문서 ID, 설비 ID 또는 본문으로 검색" /></label>
      <label>문서 종류<select value={kind} onChange={(event) => setKind(event.target.value)}>
        <option value="all">전체</option>{Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label>등록일 정렬<select value={sortOrder} onChange={(event) => setSortOrder(event.target.value)}>
        <option value="newest">최신순</option>
        <option value="oldest">오래된순</option>
      </select></label>
    </div>
    {message && <p className="manuals-notice manuals-notice--success" role="status">{message}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {searchError && <p className="error" role="alert">{searchError}</p>}
    {loading || searchPending ? <div className="panel manuals-empty" role="status">{searchPending ? '문서 제목과 본문을 검색하고 있습니다…' : '등록된 문서를 불러오고 있습니다…'}</div>
      : searchError ? <div className="panel manuals-empty"><h2>검색하지 못했습니다</h2><p>잠시 후 목록 새로고침을 눌러 다시 시도해 주세요.</p></div>
      : visible.length === 0 ? <div className="panel manuals-empty">
        <span aria-hidden="true">▤</span><h2>{documents.length ? '검색 결과가 없습니다' : '등록된 문서가 없습니다'}</h2>
        <p>{documents.length ? '검색어나 문서 종류를 바꿔서 다시 찾아보세요.' : '문서를 등록하면 제목과 검색 등록 상태를 여기서 확인할 수 있습니다.'}</p>
      </div> : <>
        <p className="manuals-count">{visible.length}개 문서</p>
        <ul className="manual-list">{visible.map((item) => {
          const failed = item.status === 'delete_failed'
          const deleting = item.status === 'deleting'
          return <li key={item.doc_id} className="manual-item">
            <div className="manual-item__icon" aria-hidden="true">▤</div>
            <div className="manual-item__body">
              <div className="manual-item__heading"><span className="manual-kind">{kinds[item.doc_type] ?? item.doc_type}</span>
                <span className={`manual-status ${failed || item.index_error ? 'manual-status--warning' : ''}`}>
                  {failed ? '삭제 실패 · 재시도 필요' : deleting ? '삭제 대기' : item.index_error ? '검색 등록 확인 필요' : item.indexed_at ? '검색 등록 완료' : '등록됨'}
                </span>
              </div>
              <h2>{item.title}</h2>
              <p className="manual-item__meta"><span>{item.doc_id}</span><span>v{item.doc_version}</span>{item.asset_id && <span>설비 {item.asset_id}</span>}</p>
              {item.uploaded_at && <p className="manual-item__date">등록 {new Date(item.uploaded_at).toLocaleString('ko-KR')}</p>}
              {term && item.search_excerpt && <p className="manual-item__excerpt"><span>본문 일치</span> {item.search_excerpt.before}<mark>{item.search_excerpt.match}</mark>{item.search_excerpt.after}</p>}
              {(failed || deleting) && <p className="manual-item__error">{item.error || '삭제가 완료되지 않았습니다. 삭제를 다시 시도해 주세요.'}</p>}
            </div>
            {canManage(user) && <button type="button" className="manual-delete-button" disabled={busy || loading}
              aria-label={`${item.title} ${failed || deleting ? '삭제 재시도' : '삭제'}`} onClick={() => setSelected(item)}>
              {failed || deleting ? '삭제 재시도' : '삭제'}
            </button>}
          </li>
        })}</ul>
      </>}
    {selected && <DeleteManualDialog document={selected} busy={busy} onCancel={() => setSelected(null)} onConfirm={() => void removeSelected()} />}
  </section>
}
