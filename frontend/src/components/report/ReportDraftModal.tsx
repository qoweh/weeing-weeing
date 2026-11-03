import { useEffect, useRef, useState } from 'react'
import {
  getIncidentAnalysis,
  getReport,
  listReports,
  saveReport,
} from '../../api/client'
import ReportForm, { type ReportIncident, type Analysis } from './ReportForm'

type DraftIncident = ReportIncident & { asset_name?: string; model?: string }
type DraftDocument = {
  report_id: string
  revision: number
  incident_id?: string | null
  incident?: DraftIncident
  asset_name?: string
  asset_id?: string
  author_name?: string
  author_id: string
  report_status: string
  data_origin?: string
  form_data?: Record<string, string | null>
  ai_analysis?: Analysis
}
import { draftValues, formValues } from './reportValues'
import './ReportDraftModal.css'

const inspector = '현장 점검자'
const statusLabels: Record<string, string> = {
  DRAFT: '초안',
  SUBMITTED: '검토 중',
  REVIEWED: '검토 승인',
  APPROVED: '작성 완료',
  REJECTED: '반려',
}

export default function ReportDraftModal({
  incident,
  reportId,
  previewOnly = false,
  user,
  onClose,
  onSaved,
  onSessionExpired,
}: {
  incident?: DraftIncident | null
  reportId?: string
  previewOnly?: boolean
  user: { role: string; employee_no: string; name: string }
  onClose: () => void
  onSaved: (saved: unknown) => void
  onSessionExpired: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [document, setDocument] = useState<DraftDocument | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [loading, setLoading] = useState(Boolean(reportId || incident))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState(false)

  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (!element.open) element.showModal()
    return () => {
      if (element.open) element.close()
    }
  }, [])

  useEffect(() => {
    if (previewOnly) {
      setAnalysis(null)
      setLoading(false)
      return
    }
    if (!reportId && !incident?.incident_id) {
      setLoading(false)
      return
    }
    let active = true
    async function loadDraft() {
      setLoading(true)
      setError('')
      try {
        let selectedId: string | undefined = reportId
        if (!selectedId && incident?.incident_id) {
          const reports = await listReports('all')
          selectedId = reports.find(
            (report) =>
              report.incident_id === incident.incident_id &&
              report.report_status === 'DRAFT',
          )?.report_id
        }
        const [saved, analysisResult] = await Promise.all([
          selectedId ? getReport(selectedId) : Promise.resolve(null),
          incident?.incident_id
            ? getIncidentAnalysis(incident.incident_id).catch(() => null)
            : Promise.resolve(null),
        ])
        if (!active) return
        setDocument(saved)
        setAnalysis(saved?.ai_analysis || analysisResult?.analysis || null)
      } catch (failure) {
        if (!active) return
        setError(
          failure instanceof Error
            ? failure.message
            : '보고서 처리에 실패했습니다.',
        )
        setLoadError(true)
        if (
          failure instanceof Error &&
          'status' in failure &&
          failure.status === 401
        )
          onSessionExpired()
      } finally {
        if (active) setLoading(false)
      }
    }
    loadDraft()
    return () => {
      active = false
    }
  }, [incident, reportId, previewOnly, onSessionExpired])

  const canEdit =
    previewOnly ||
    (user?.role === inspector &&
      (!document ||
        (document.author_id === user.employee_no &&
          document.report_status === 'DRAFT')))

  const reportForm = (canEdit || document) && (
    <ReportForm
      key={
        document
          ? `${document.report_id}:${document.revision}`
          : incident?.incident_id
      }
      incident={document?.incident || incident}
      analysis={analysis}
      reportId={document?.report_id || ''}
      assetName={
        document?.asset_name ||
        document?.asset_id ||
        incident?.asset_name ||
        incident?.model ||
        ''
      }
      savedValues={formValues(document)}
      author={{
        name: document?.author_name || user.name,
        employee_no: document?.author_id || user.employee_no,
      }}
      statusLabel={statusLabels[document?.report_status || ''] || '초안'}
      readOnly={!canEdit}
      busy={busy}
      onSave={canEdit && !previewOnly ? saveAndClose : undefined}
      saveOnly={canEdit && !previewOnly}
      saveOnlyLabel="저장 후 완료"
    />
  )

  async function saveAndClose(values: Record<string, string>) {
    if (busy || !canEdit) return
    setBusy(true)
    setError('')
    try {
      const payload = {
        incident_id: document?.incident_id || incident?.incident_id || null,
        data_origin: document?.data_origin || 'LIVE',
        form_data: draftValues(values),
        ...(document ? { expected_revision: document.revision } : {}),
      }
      const saved = await saveReport(document?.report_id, payload)
      onSaved(saved)
      onClose()
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : '보고서 처리에 실패했습니다.',
      )
      if (
        failure instanceof Error &&
        'status' in failure &&
        failure.status === 401
      )
        onSessionExpired()
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog
      ref={dialog}
      className="report-draft-dialog"
      aria-labelledby="report-draft-title"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <header className="report-draft-dialog__header">
        <div>
          <p>
            {previewOnly
              ? '정비 이력 · 보고서 디자인 미리보기'
              : '정비 이력 · 보고서 초안'}
          </p>
          <h2 id="report-draft-title">
            {previewOnly
              ? '새 정비 보고서'
              : incident?.incident_id || '사건 보고서'}
          </h2>
        </div>
        <button
          type="button"
          className="report-draft-dialog__close"
          aria-label="보고서 초안 닫기"
          onClick={onClose}
        >
          ×
        </button>
      </header>
      {loading ? (
        <p className="report-draft-dialog__state" role="status">
          사건과 기존 초안을 불러오는 중입니다.
        </p>
      ) : loadError ? (
        <p className="report-draft-dialog__error" role="alert">
          {error}
        </p>
      ) : !canEdit ? (
        <>
          <p className="report-draft-dialog__state" role="status">
            {document
              ? '읽기 전용 보고서입니다. 수정은 작성자와 현장 점검자만 할 수 있습니다.'
              : '새 보고서는 현장 점검자만 작성할 수 있습니다.'}
          </p>
          {reportForm}
        </>
      ) : (
        <>
          {previewOnly && (
            <p className="report-draft-dialog__state" role="status">
              디자인 확인용 미리보기입니다. 입력 내용은 저장되지 않습니다.
            </p>
          )}
          {error && (
            <p className="report-draft-dialog__error" role="alert">
              {error}
            </p>
          )}
          {reportForm}
        </>
      )}
    </dialog>
  )
}
