import { useEffect, useRef, useState } from 'react'
import { fetchDocumentFile } from '../../api/client'
import Button from './Button'
import { dateLabel } from './library'
import './DocumentPdfModal.css'

export default function DocumentPdfModal({
  doc,
  onClose,
  onSessionExpired,
  onDelete,
}) {
  const dialog = useRef(null)
  const [url, setUrl] = useState(doc.file || '')
  const [loading, setLoading] = useState(!doc.file && Boolean(doc.upload_id))
  const [error, setError] = useState(
    !doc.file && !doc.upload_id ? '웹에서 등록한 문서만 원문을 볼 수 있습니다.' : '',
  )

  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (!element.open) element.showModal()
    return () => {
      if (element.open) element.close()
    }
  }, [])

  useEffect(() => {
    if (doc.file || !doc.upload_id) return
    let active = true
    let objectUrl = ''
    setLoading(true)
    setError('')
    fetchDocumentFile(doc.upload_id)
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(
          blob.type === 'application/pdf'
            ? blob
            : new Blob([blob], { type: 'application/pdf' }),
        )
        setUrl(objectUrl)
      })
      .catch((failure) => {
        if (!active) return
        setError(failure.message)
        if (failure.status === 401) onSessionExpired?.()
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [doc, onSessionExpired])

  return (
    <dialog
      ref={dialog}
      className="pdf-modal"
      aria-labelledby="pdf-modal-title"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <header className="pdf-modal__header">
        <div className="pdf-modal__title">
          <h2 id="pdf-modal-title">{doc.name}</h2>
          <p>
            {[
              doc.asset,
              doc.version,
              doc.date && dateLabel(doc.date),
              doc.status,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <div className="pdf-modal__actions">
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer">
              새 탭에서 열기
            </a>
          )}
          {onDelete && (
            <Button
              type="button"
              className="pdf-modal__delete"
              onClick={onDelete}
            >
              삭제
            </Button>
          )}
          <Button type="button" aria-label="PDF 보기 닫기" onClick={onClose}>
            닫기
          </Button>
        </div>
      </header>
      <div className="pdf-modal__body">
        {loading ? (
          <p role="status">문서 원문을 불러오는 중입니다.</p>
        ) : error ? (
          <p role="alert">{error}</p>
        ) : (
          <iframe title={`${doc.name} PDF`} src={url} />
        )}
      </div>
    </dialog>
  )
}
