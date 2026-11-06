import { useEffect, useRef, useState } from "react";
import { getIncidentAnalysis } from "../../api/client";
import type { Analysis } from "./ReportForm";
import "./AnalysisModal.css";
import ReportAnalysisSection from "./ReportAnalysisSection";

export default function AnalysisModal({
  incidentId,
  onClose,
  onWrite,
  onSessionExpired,
}: {
  incidentId: string;
  onClose: () => void;
  onWrite: () => void;
  onSessionExpired: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [result, setResult] = useState<{
    job: { status: string } | null;
    analysis: Analysis | null;
  } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
    let active = true;
    getIncidentAnalysis(incidentId)
      .then((data) => {
        if (active) setResult(data);
      })
      .catch((failure) => {
        if (!active) return;
        if (failure.status === 401) onSessionExpired();
        else
          setError(
            "분석 결과를 불러오지 못했습니다. 창을 닫고 다시 시도해 주세요.",
          );
      });
    return () => {
      active = false;
    };
  }, [incidentId, onSessionExpired]);
  const analysis =
    result?.analysis?.incident_id === incidentId ? result.analysis : null;
  const pending =
    result?.job && ["PENDING", "RUNNING"].includes(result.job.status);
  return (
    <dialog
      ref={dialog}
      className="analysis-dialog"
      aria-labelledby="analysis-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header>
        <div>
          <p>{incidentId}</p>
          <h2 id="analysis-title">AI 분석 및 대응 권고</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="닫기">
          ×
        </button>
      </header>
      <div
        className="analysis-dialog__body"
        role="region"
        aria-label="AI 분석 내용"
        tabIndex={0}
      >
        {error && (
          <p className="analysis-dialog__state" role="alert">
            {error}
          </p>
        )}
        {!error && !result && (
          <p className="analysis-dialog__state" role="status">
            분석 결과를 불러오는 중입니다.
          </p>
        )}
        {pending && (
          <p className="analysis-dialog__state" role="status">
            분석이 진행 중입니다. 잠시 후 다시 확인해 주세요.
          </p>
        )}
        {!pending && result?.job?.status === "FAILED" && (
          <p className="analysis-dialog__state" role="alert">
            분석 작업이 실패했습니다. 표시되는 결과는 이전 분석일 수 있습니다.
          </p>
        )}
        <div className="report-sheet analysis-dialog__sheet">
          <ReportAnalysisSection
            analysis={pending ? null : (analysis ?? null)}
            showTitle={false}
          />
        </div>
      </div>
      <footer>
        <button type="button" onClick={onClose}>
          닫기
        </button>
        <button type="button" onClick={onWrite}>
          보고서 작성
        </button>
      </footer>
    </dialog>
  );
}
