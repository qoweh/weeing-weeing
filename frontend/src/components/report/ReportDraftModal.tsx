import { useEffect, useRef, useState } from "react";
import {
  actOnReport,
  deleteReport,
  getIncidentReportContext,
  getReport,
  listReports,
  saveReport,
} from "../../api/client";
import ReportForm, {
  type ReportIncident,
  type Analysis,
  type ReportTelemetry,
} from "./ReportForm";

type DraftIncident = ReportIncident & { asset_name?: string; model?: string };
type DraftDocument = {
  report_id: string;
  revision: number;
  incident_id?: string | null;
  incident?: DraftIncident;
  asset_name?: string;
  asset_id?: string;
  author_name?: string;
  author_id: string;
  report_status: string;
  report_version: number;
  current_version: number;
  updated_at?: string;
  index_status?: string;
  approval?: {
    step: number;
    role: string;
    user: string;
    decision: string;
    at: string;
    comment?: string | null;
  }[];
  data_origin?: string;
  form_data?: Record<string, string | null>;
  ai_analysis?: Analysis;
};
import { draftValues, formValues } from "./reportValues";
import "./ReportDraftModal.css";
import { canControl, canWriteReports, reviewStep } from "../auth/permissions";

const statusLabels: Record<string, string> = {
  DRAFT: "초안",
  SUBMITTED: "검토 중",
  REVIEWED: "검토 승인",
  APPROVED: "작성 완료",
  REJECTED: "반려",
};

export default function ReportDraftModal({
  incident,
  reportId,
  version,
  previewOnly = false,
  user,
  onClose,
  onSaved,
  onDecisionComplete,
  onSessionExpired,
}: {
  incident?: DraftIncident | null;
  reportId?: string;
  version?: number;
  previewOnly?: boolean;
  user: {
    role: string;
    employee_no: string;
    name: string;
    is_admin?: boolean;
  };
  onClose: () => void;
  onSaved: (saved: unknown) => void;
  onDecisionComplete: (message: string) => void;
  onSessionExpired: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [document, setDocument] = useState<DraftDocument | null>(null);
  const [resolvedReportId, setResolvedReportId] = useState(reportId);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [context, setContext] = useState<{
    incident: ReportIncident;
    analysis_incident: ReportIncident | null;
    telemetry: ReportTelemetry | null;
    telemetry_anchor: string | null;
    telemetry_notes: string[];
  } | null>(null);
  const [loading, setLoading] = useState(Boolean(reportId || incident));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<number | undefined>(
    version,
  );
  const [comment, setComment] = useState("");
  const [message, setMessage] = useState("");
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!element.open) element.showModal();
    return () => {
      if (element.open) element.close();
    };
  }, []);

  useEffect(() => {
    if (previewOnly) {
      setAnalysis(null);
      setContext(null);
      setLoading(false);
      return;
    }
    if (!resolvedReportId && !incident?.incident_id) {
      setLoading(false);
      return;
    }
    let active = true;
    async function loadDraft() {
      setLoading(true);
      setError("");
      setLoadError(false);
      setContext(null);
      try {
        let selectedId: string | undefined = resolvedReportId;
        if (!selectedId && incident?.incident_id) {
          const reports = await listReports("all");
          selectedId = reports.find(
            (report) =>
              report.incident_id === incident.incident_id &&
              report.report_status === "DRAFT",
          )?.report_id;
        }
        const saved = selectedId
          ? await getReport(selectedId, selectedVersion)
          : null;
        const id = saved?.incident_id || incident?.incident_id;
        if (!id) throw new Error("연결 사건이 없습니다.");
        const reportContext = await getIncidentReportContext(id, selectedId);
        if (
          reportContext.incident?.incident_id !== id ||
          (saved?.incident_id &&
            incident?.incident_id &&
            saved.incident_id !== incident.incident_id)
        ) {
          throw new Error("보고서와 조회한 사건이 일치하지 않습니다.");
        }
        if (!active) return;
        const historical = Boolean(
          selectedVersion &&
          saved &&
          reportContext.document?.report_version !== selectedVersion,
        );
        setDocument(historical ? saved : reportContext.document || null);
        setAnalysis(
          historical
            ? saved?.ai_analysis || null
            : reportContext.analysis || null,
        );
        setContext(
          historical
            ? {
                ...reportContext,
                analysis_incident: saved?.incident || null,
                telemetry: null,
                telemetry_notes: [
                  "이전 보고서 판본에 연결된 센서 표본은 표시하지 않습니다.",
                ],
              }
            : reportContext,
        );
      } catch (failure) {
        if (!active) return;
        setError(
          failure instanceof Error
            ? failure.message
            : "보고서 처리에 실패했습니다.",
        );
        setLoadError(true);
        if (
          failure instanceof Error &&
          "status" in failure &&
          failure.status === 401
        )
          onSessionExpired();
      } finally {
        if (active) setLoading(false);
      }
    }
    loadDraft();
    return () => {
      active = false;
    };
  }, [
    incident,
    resolvedReportId,
    selectedVersion,
    previewOnly,
    onSessionExpired,
  ]);

  useEffect(() => {
    if (
      !document ||
      document.index_status !== "pending" ||
      document.report_version !== document.current_version
    )
      return;
    let active = true;
    const id = document.report_id;
    const revision = document.revision;
    const timer = setTimeout(async () => {
      try {
        const latest = await getReport(id);
        if (active)
          setDocument((current) =>
            current?.report_id === id &&
            current.revision === revision &&
            current.report_version === latest.report_version
              ? latest
              : current,
          );
      } catch (failure) {
        if (!active) return;
        if (
          failure &&
          typeof failure === "object" &&
          "status" in failure &&
          failure.status === 401
        )
          onSessionExpired();
        else setError("검색 자료 등록 상태를 불러오지 못했습니다.");
      }
    }, 3000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [document, onSessionExpired]);

  const canEdit =
    previewOnly ||
    (canWriteReports(user) &&
      (!document ||
        (document.author_id === user.employee_no &&
          document.report_version === document.current_version &&
          document.report_status === "DRAFT")));

  const current =
    document && document.report_version === document.current_version;
  const own = document?.author_id === user.employee_no;
  // 관리자는 두 결재 단계를 모두 할 수 있어 직책이 아닌 보고서 상태로 단계를 정한다.
  const step =
    document && current && !own
      ? reviewStep(user, document.report_status)
      : null;
  const reviewable = step !== null;

  const reportForm = (canEdit || document) && (
    <ReportForm
      key={
        document
          ? `${document.report_id}:${document.report_version}:${document.revision}`
          : incident?.incident_id
      }
      incident={document?.incident || context?.incident || incident}
      analysis={analysis}
      analysisInput={context?.analysis_incident}
      telemetry={context?.telemetry}
      telemetryAnchor={context?.telemetry_anchor}
      telemetryNotes={context?.telemetry_notes}
      reportId={document?.report_id || ""}
      assetName={
        document?.asset_name ||
        document?.asset_id ||
        incident?.asset_name ||
        incident?.model ||
        ""
      }
      savedValues={formValues(document)}
      author={{
        name: document?.author_name || user.name,
        employee_no: document?.author_id || user.employee_no,
      }}
      statusLabel={statusLabels[document?.report_status || ""] || "초안"}
      readOnly={!canEdit}
      busy={busy}
      onSave={
        canEdit && !previewOnly ? (values) => persist(values, false) : undefined
      }
      onSubmit={
        canEdit && !previewOnly ? (values) => persist(values, true) : undefined
      }
      saveOnly={previewOnly}
    />
  );

  async function persist(values: Record<string, string>, submit: boolean) {
    if (busy || !canEdit) return;
    setBusy(true);
    setError("");
    try {
      const payload = {
        incident_id: document?.incident_id || incident?.incident_id || null,
        data_origin: document?.data_origin || "LIVE",
        form_data: draftValues(values),
        ...(document ? { expected_revision: document.revision } : {}),
      };
      let saved = await saveReport(document?.report_id, payload);
      setDocument(saved);
      onSaved(saved);
      if (submit) {
        saved = await actOnReport(saved.report_id, "submit", saved.revision);
        setDocument(saved);
        onSaved(saved);
      }
      setResolvedReportId(saved.report_id);
      onDecisionComplete(
        submit ? "보고서를 제출했습니다." : "보고서를 임시 저장했습니다.",
      );
      onClose();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "보고서 처리에 실패했습니다.",
      );
      if (
        failure instanceof Error &&
        "status" in failure &&
        failure.status === 401
      )
        onSessionExpired();
    } finally {
      setBusy(false);
    }
  }

  async function decide(action: string) {
    if (!document || busy) return;
    setBusy(true);
    setError("");
    try {
      const changed = await actOnReport(
        document.report_id,
        action,
        document.revision,
        comment,
      );
      setDocument(changed);
      setSelectedVersion(undefined);
      setComment("");
      setMessage(
        action === "revise"
          ? "반려된 보고서를 수정할 수 있습니다."
          : "결재 결과를 저장했습니다.",
      );
      onSaved(changed);
      if (["review", "approve", "reject"].includes(action)) {
        onDecisionComplete(
          action === "reject"
            ? "보고서를 반려했습니다."
            : action === "review"
              ? "검토 승인이 완료되었습니다."
              : "최종 승인이 완료되었습니다.",
        );
        onClose();
      }
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "보고서 처리에 실패했습니다.",
      );
      if (
        failure &&
        typeof failure === "object" &&
        "status" in failure &&
        failure.status === 401
      )
        onSessionExpired();
    } finally {
      setBusy(false);
    }
  }

  async function removeReport(draft: boolean) {
    if (!document || busy) return;
    const prompt =
      draft && document.report_version > 1
        ? "수정 중인 내용을 삭제하고 이전 반려 보고서로 돌아갈까요?"
        : draft
          ? "임시 저장한 보고서를 삭제할까요?"
          : "승인된 보고서와 모든 버전, 결재 이력 및 검색 자료를 삭제할까요?";
    if (!window.confirm(prompt)) return;
    setBusy(true);
    setError("");
    try {
      const result = await deleteReport(
        document.report_id,
        document.revision,
        draft,
      );
      onSaved(result);
      if (result.report) {
        setDocument(result.report);
        setMessage("수정이 취소되었습니다.");
      } else onClose();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "보고서 삭제에 실패했습니다.",
      );
      if (
        failure &&
        typeof failure === "object" &&
        "status" in failure &&
        failure.status === 401
      )
        onSessionExpired();
    } finally {
      setBusy(false);
    }
  }

  async function downloadPdf() {
    if (!document || downloading || !dialog.current) return;
    setDownloading(true);
    setError("");
    try {
      const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
        import("html2canvas"),
        import("jspdf"),
      ]);
      const parts = dialog.current.querySelectorAll<HTMLElement>(
        ".report-sheet, .report-draft-dialog__section-title, .report-draft-dialog__history",
      );
      if (!parts.length) throw new Error("보고서 내용을 찾을 수 없습니다.");
      await window.document.fonts.ready;
      const pdf = new jsPDF({ unit: "mm", format: "a4" });
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const margin = 10;
      const width = pageWidth - margin * 2;
      let y = margin;
      for (const part of parts) {
        const canvas = await html2canvas(part, {
          scale: 2,
          backgroundColor: "#ffffff",
          useCORS: true,
          windowWidth: Math.max(part.scrollWidth, 1000),
        });
        let top = 0;
        while (top < canvas.height) {
          let available = pageHeight - margin - y;
          if (available < 15) {
            pdf.addPage();
            y = margin;
            available = pageHeight - margin * 2;
          }
          const height = Math.min(
            canvas.height - top,
            Math.floor((available * canvas.width) / width),
          );
          const slice = window.document.createElement("canvas");
          slice.width = canvas.width;
          slice.height = height;
          const context = slice.getContext("2d");
          if (!context) throw new Error("PDF 이미지를 만들 수 없습니다.");
          context.drawImage(
            canvas,
            0,
            top,
            canvas.width,
            height,
            0,
            0,
            canvas.width,
            height,
          );
          const renderedHeight = (height * width) / canvas.width;
          pdf.addImage(
            slice.toDataURL("image/png"),
            "PNG",
            margin,
            y,
            width,
            renderedHeight,
          );
          top += height;
          y += renderedHeight;
          if (top < canvas.height) {
            pdf.addPage();
            y = margin;
          }
        }
        y += 3;
      }
      pdf.save(`${document.report_id}.pdf`);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? `PDF 다운로드 실패: ${failure.message}`
          : "PDF 다운로드에 실패했습니다.",
      );
    } finally {
      setDownloading(false);
    }
  }

  const permissionNotice = !loading && !loadError && !canEdit && !document;

  return (
    <dialog
      ref={dialog}
      className={`report-draft-dialog${permissionNotice ? " report-draft-dialog--notice" : ""}`}
      aria-labelledby="report-draft-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        // 초안을 작성·수정하는 중에는 모달 바깥을 눌러도 닫히지 않는다(실수로 입력을 잃지 않게).
        // 닫기는 오른쪽 위 × 버튼이나 Esc로만 한다. 읽기 전용·권한 안내 화면은 바깥 클릭으로 닫힌다.
        if (event.target === event.currentTarget && !canEdit) onClose();
      }}
    >
      {!permissionNotice && (
        <header className="report-draft-dialog__header">
          <h2 id="report-draft-title" className="report-sr-only">
            {previewOnly ? "새 정비 보고서" : "보고서 초안"}
          </h2>
          {document?.report_status === "APPROVED" && !loading && !loadError && (
            <button
              type="button"
              className="report-draft-dialog__download"
              onClick={() => void downloadPdf()}
              disabled={downloading}
              aria-label="보고서 PDF 다운로드"
              title="PDF 다운로드"
            >
              {downloading ? (
                "생성 중"
              ) : (
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 3v12m-4-4 4 4 4-4M4 17v3h16v-3" />
                </svg>
              )}
            </button>
          )}
          <button
            type="button"
            className="report-draft-dialog__close"
            aria-label="보고서 초안 닫기"
            onClick={onClose}
          >
            ×
          </button>
        </header>
      )}
      {permissionNotice ? (
        <div className="report-draft-dialog__notice" role="alert">
          <span className="report-draft-dialog__notice-icon" aria-hidden="true">
            !
          </span>
          <h2 id="report-draft-title">보고서 작성 권한 안내</h2>
          <p>
            새 보고서는 현장 점검자·보전 팀장·계정 관리자가 작성할 수 있습니다.
          </p>
          <button type="button" onClick={onClose} autoFocus>
            확인
          </button>
        </div>
      ) : loading ? (
        <p className="report-draft-dialog__state" role="status">
          사건과 기존 초안을 불러오는 중입니다.
        </p>
      ) : loadError ? (
        <p className="report-draft-dialog__error" role="alert">
          {error}
        </p>
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
          {message && (
            <p className="report-draft-dialog__state" role="status">
              {message}
            </p>
          )}
          {document?.report_status === "APPROVED" && reportForm}
          {document && (
            <>
              {document.report_status === "APPROVED" && (
                <h3 className="report-draft-dialog__section-title">
                  <span>07</span>결재 이력
                </h3>
              )}
              <section
                className="report-draft-dialog__history"
                aria-label="보고서 버전 및 결재 이력"
              >
                {document.report_status !== "APPROVED" && (
                  <h3>
                    {document.report_id} · v{document.report_version} ·{" "}
                    {statusLabels[document.report_status] ||
                      document.report_status}
                  </h3>
                )}
                {!current && (
                  <p>
                    이전 버전입니다. 현재 버전은 v{document.current_version}이며
                    조회만 할 수 있습니다.
                  </p>
                )}
                <div
                  className="report-draft-dialog__actions"
                  aria-label="보고서 버전 선택"
                >
                  {document.report_status !== "APPROVED" &&
                    Array.from(
                      { length: document.current_version },
                      (_, index) => index + 1,
                    ).map((item) => (
                      <button
                        key={item}
                        type="button"
                        disabled={busy}
                        aria-pressed={document.report_version === item}
                        onClick={() => {
                          setMessage("");
                          setSelectedVersion(item);
                        }}
                      >
                        v{item} 보기
                      </button>
                    ))}
                  {document.report_status !== "APPROVED" && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setMessage("");
                        setSelectedVersion(undefined);
                      }}
                    >
                      최신 내용 보기
                    </button>
                  )}
                  {own &&
                    current &&
                    canWriteReports(user) &&
                    document.report_status === "REJECTED" && (
                      <button
                        className="report-draft-dialog__revise"
                        type="button"
                        disabled={busy}
                        onClick={() => void decide("revise")}
                      >
                        보고서 수정하기
                      </button>
                    )}
                  {own &&
                    current &&
                    canWriteReports(user) &&
                    document.report_status === "DRAFT" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void removeReport(true)}
                      >
                        {document.report_version > 1
                          ? "수정 취소"
                          : "임시 저장 삭제"}
                      </button>
                    )}
                </div>
                {document.report_status !== "APPROVED" && <h4>결재 이력</h4>}
                {document.approval?.length ? (
                  <ol className="report-draft-dialog__approvals">
                    {document.approval.map((item, index) => (
                      <li
                        key={`${item.step}-${index}`}
                        className={
                          item.decision === "반려"
                            ? "is-rejected"
                            : item.decision === "승인"
                              ? "is-approved"
                              : "is-submitted"
                        }
                      >
                        <div>
                          <strong className="report-draft-dialog__approval-badge">
                            {item.decision === "승인" &&
                            item.role === "관제 담당자"
                              ? "최종 승인"
                              : item.decision}
                          </strong>{" "}
                          <strong>{item.role}</strong> · {item.user}{" "}
                          <time dateTime={item.at}>
                            {Number.isNaN(new Date(item.at).getTime())
                              ? item.at
                              : new Date(item.at).toLocaleString("ko-KR")}
                          </time>
                        </div>
                        {item.comment && (
                          <p>
                            <b>
                              {item.decision === "반려"
                                ? "반려 사유"
                                : "결재 의견"}
                              :{" "}
                            </b>
                            {item.comment}
                          </p>
                        )}
                      </li>
                    ))}
                    {document.index_status === "indexed" && (
                      <li>
                        <strong className="report-draft-dialog__approval-badge report-draft-dialog__index-badge">
                          검색 자료 등록 완료
                        </strong>
                      </li>
                    )}
                  </ol>
                ) : (
                  <p>결재 이력이 없습니다.</p>
                )}
                {document.index_status === "pending" && (
                  <p>검색 자료 등록 대기 중입니다.</p>
                )}
                {document.index_status === "indexed" &&
                  !document.approval?.length && (
                    <ol className="report-draft-dialog__approvals">
                      <li>
                        <strong className="report-draft-dialog__approval-badge report-draft-dialog__index-badge">
                          검색 자료 등록 완료
                        </strong>
                      </li>
                    </ol>
                  )}
                {document.index_status === "failed" && (
                  <p>
                    검색 자료 등록에 실패했습니다. 관리자에게 재처리를
                    요청하세요.
                  </p>
                )}
              </section>
              {current &&
                canControl(user) &&
                document.report_status === "APPROVED" && (
                  <div className="report-draft-dialog__actions report-draft-dialog__delete-actions">
                    <button
                      className="report-draft-dialog__delete"
                      type="button"
                      disabled={busy}
                      onClick={() => void removeReport(false)}
                    >
                      보고서 삭제
                    </button>
                  </div>
                )}
            </>
          )}
          {document?.report_status !== "APPROVED" && reportForm}
          {reviewable && (
            <section className="report-draft-dialog__history">
              <h3>보고서 결재</h3>
              <label>
                결재 의견 — 반려 시 필수
                <textarea
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  maxLength={2000}
                  disabled={busy}
                />
              </label>
              <div className="report-draft-dialog__actions report-draft-dialog__review-actions">
                <button
                  className="report-draft-dialog__reject"
                  type="button"
                  disabled={busy || !comment.trim()}
                  onClick={() => void decide("reject")}
                >
                  반려
                </button>
                <button
                  className="report-draft-dialog__approve"
                  type="button"
                  disabled={busy}
                  onClick={() => step && void decide(step)}
                >
                  {step === "review" ? "검토 승인" : "최종 승인"}
                </button>
              </div>
            </section>
          )}
        </>
      )}
    </dialog>
  );
}
