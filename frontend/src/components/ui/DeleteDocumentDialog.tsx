import { useEffect, useId, useRef } from 'react'
import Button from './Button'
import './DeleteDocumentDialog.css'

export default function DeleteDocumentDialog({
  doc,
  busy,
  onCancel,
  onConfirm,
}: {
  doc: { name: string }
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancelButton = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    const element = dialog.current
    const previousFocus = window.document.activeElement
    if (element && !element.open) element.showModal()
    cancelButton.current?.focus()
    return () => {
      if (element?.open) element.close()
      if (previousFocus instanceof HTMLElement) previousFocus.focus()
    }
  }, [])

  return (
    <dialog
      ref={dialog}
      className="delete-dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onCancel()
      }}
    >
      <h2 id={titleId}>문서를 삭제할까요?</h2>
      <p className="delete-dialog__name">{doc.name}</p>
      <p id={descriptionId}>
        이 문서의 모든 버전에 해당하는 검색 자료도 함께 삭제됩니다. 삭제가
        완료되면 검색과 AI 답변의 근거로 사용되지 않습니다.
      </p>
      <div className="delete-dialog__actions">
        <Button
          ref={cancelButton}
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          취소
        </Button>
        <Button
          type="button"
          className="delete-dialog__confirm"
          disabled={busy}
          onClick={onConfirm}
        >
          {busy ? '삭제 중…' : '삭제하기'}
        </Button>
      </div>
    </dialog>
  )
}
