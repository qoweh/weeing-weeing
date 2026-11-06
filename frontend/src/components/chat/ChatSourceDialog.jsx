import { useEffect, useRef, useState } from "react";
import IncidentCodes from "../ui/IncidentCodeLabel";
import { getChatDocumentFile } from "../../api/chat.js";
import { getReport } from "../../api/client.js";
import "./chat.scss";

const formLabels = {
  department: "부서",
  process_impact: "공정 영향",
  actual_actions: "실제 조치",
  action_at: "조치 시각",
  replaced_parts: "교체 부품",
  cause_category: "원인 분류",
  confirmed_cause: "확인 원인",
  cause_evidence: "확인 근거",
  ai_assessment: "AI 의견 평가",
  trial_result: "복구 시험 결과",
  trial_details: "시험 상세",
  downtime_start: "정지 시작",
  downtime_end: "운전 복귀",
  resolution: "처리 결과",
  follow_up: "후속 조치",
  follow_up_owner: "후속 담당",
  follow_up_due: "후속 기한",
};

export default function ChatSourceDialog({
  source,
  onClose,
  onSessionExpired,
}) {
  const dialog = useRef(null);
  const [data, setData] = useState(null);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!dialog.current.open) dialog.current.showModal();
    const controller = new AbortController();
    let objectUrl = "";
    async function load() {
      try {
        if (source.kind === "DOCUMENT") {
          const blob = await getChatDocumentFile(source, controller.signal);
          if (controller.signal.aborted) return;
          objectUrl = URL.createObjectURL(
            new Blob([blob], { type: "application/pdf" }),
          );
          setUrl(
            objectUrl +
              (Number.isInteger(source.page) ? `#page=${source.page}` : ""),
          );
        } else {
          const report = await getReport(
            source.report_id,
            source.report_version,
            controller.signal,
          );
          if (!controller.signal.aborted) setData(report);
        }
      } catch (failure) {
        if (controller.signal.aborted) return;
        if (failure.status === 401) onSessionExpired();
        else setError(failure.message);
      }
    }
    load();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [source, onSessionExpired]);
  return (
    <dialog
      ref={dialog}
      className="chat-source-dialog"
      aria-labelledby="chat-source-title"
      onCancel={onClose}
    >
      <header>
        <div>
          <h2 id="chat-source-title">{source.title}</h2>
          <p>
            {source.kind === "DOCUMENT"
              ? `${source.doc_id} v${source.doc_version}`
              : `${source.report_id} v${source.report_version}`}
          </p>
        </div>
        <button type="button" onClick={onClose}>
          닫기
        </button>
      </header>
      {error ? (
        <p role="alert">{error}</p>
      ) : url ? (
        <iframe src={url} title={`${source.title} 원문 PDF`} />
      ) : data ? (
        <div className="chat-source-dialog__report">
          <p>
            보고서 상태: {data.report_status} · 설비: {data.incident?.asset_id}{" "}
            · 알람: <IncidentCodes codes={data.incident?.codes} />
          </p>
          <dl>
            {Object.entries(formLabels).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{data.form_data?.[key] || "기록 없음"}</dd>
              </div>
            ))}
          </dl>
          {data.incident && (
            <section>
              <h3>사건 관측 근거</h3>
              <p>
                발생: {data.incident.first_detected_at} / 확정:{" "}
                {data.incident.confirmed_at || "기록 없음"} / 관측 회복:{" "}
                {data.incident.recovered_at || "기록 없음"}
              </p>
              {data.incident.evidence?.map((item, index) => (
                <p key={index}>
                  {item.field}: {String(item.value ?? "미수집")}{" "}
                  {item.unit || ""}
                  <br />
                  {item.threshold} {item.observed}
                </p>
              ))}
            </section>
          )}
          {data.approval?.length > 0 && (
            <section>
              <h3>검토·확정 이력</h3>
              <ul>
                {data.approval.map((step, index) => (
                  <li key={index}>
                    {step.role} · {step.user} · {step.decision} · {step.at}
                    {step.comment ? ` — ${step.comment}` : ""}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {data.ai_analysis && (
            <section>
              <h3>분석·점검 권고</h3>
              <p>{data.ai_analysis.observed_facts}</p>
              {data.ai_analysis.suspected_causes?.map((cause, i) => (
                <p key={i}>
                  {cause.cause} — {cause.basis}
                </p>
              ))}
              <ol>
                {data.ai_analysis.recommended_checks?.map((text, i) => (
                  <li key={i}>{text}</li>
                ))}
              </ol>
            </section>
          )}
        </div>
      ) : (
        <p role="status">인용한 원문을 불러오는 중입니다.</p>
      )}
    </dialog>
  );
}
