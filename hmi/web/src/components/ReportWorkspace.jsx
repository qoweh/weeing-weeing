import { useEffect, useState } from "react";

import {
  actOnReport, deleteReport, getReport, listIncidents, saveReport,
} from "../api/client";
import ReportForm from "./ReportForm";
import { draftValues, formValues } from "./reportValues";
import "./ReportWorkspace.css";

const statuses = { DRAFT: "작성 중", SUBMITTED: "제출됨", REVIEWED: "최종 승인 대기", APPROVED: "최종 승인", REJECTED: "반려" };
const inspector = "현장 점검자";
const lead = "보전 팀장";
const control = "관제 담당자";

export default function ReportWorkspace({ user, onSessionExpired, onBusyChange, initialDocument = null, initialIncidentId = "", onNavigate, active = true }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [incidents, setIncidents] = useState([]);
  const [document, setDocument] = useState(initialDocument);
  const [incidentId, setIncidentId] = useState(initialDocument?.incident_id ?? initialIncidentId ?? "");
  const [origin, setOrigin] = useState(initialDocument?.data_origin ?? "LIVE");
  const [comment, setComment] = useState("");

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    listIncidents()
      .then((available) => {
        if (cancelled) return;
        setIncidents(available);
      }).catch((failure) => {
        if (cancelled) return;
        setError(failure.message);
        if (failure.status === 401) onSessionExpired();
      });
    return () => { cancelled = true; };
  }, [user, onSessionExpired]);

  const pendingReportId = document?.index_status === "pending" && document.report_version === document.current_version ? document.report_id : null;
  const pendingRevision = document?.revision;
  const pendingVersion = document?.report_version;
  useEffect(() => {
    if (!active || !pendingReportId) return;
    let cancelled = false;
    let timer;
    const reportId = pendingReportId;
    const revision = pendingRevision;
    const version = pendingVersion;

    async function refreshIndexStatus() {
      try {
        const latest = await getReport(reportId);
        if (cancelled) return;
        setDocument((current) => current?.report_id === reportId && current.revision === revision && current.report_version === version ? latest : current);
        if (latest.index_status === "pending") timer = setTimeout(refreshIndexStatus, 3000);
      } catch (failure) {
        if (cancelled) return;
        if (failure.status === 401) onSessionExpired();
        setError("검색 자료 등록 상태를 불러오지 못했습니다. 최신 내용 불러오기를 눌러 확인해 주세요.");
      }
    }
    timer = setTimeout(refreshIndexStatus, 3000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [active, pendingReportId, pendingRevision, pendingVersion, onSessionExpired]);

  async function run(operation) {
    if (busy) return null;
    setBusy(true);
    onBusyChange(true);
    setError("");
    setMessage("");
    try {
      return await operation();
    } catch (failure) {
      if (failure.status === 401) onSessionExpired();
      setError(failure.message);
      return null;
    } finally {
      setBusy(false);
      onBusyChange(false);
    }
  }

  function selectDocument(value) {
    setDocument(value);
    setIncidentId(value?.incident_id ?? "");
    setOrigin(value?.data_origin ?? "LIVE");
    setComment("");
  }

  async function refreshAfterAction(changed) {
    selectDocument(changed);
    try {
      const latest = await getReport(changed.report_id);
      selectDocument(latest);
    } catch (failure) {
      if (failure.status === 401) onSessionExpired();
      else setError("처리는 완료됐지만 최신 내용을 불러오지 못했습니다. 최신 내용 불러오기를 눌러 확인해 주세요.");
    }
  }

  async function persist(values) {
    const payload = {
      incident_id: incidentId || null,
      data_origin: origin,
      form_data: draftValues(values),
      ...(document ? { expected_revision: document.revision } : {}),
    };
    const saved = await saveReport(document?.report_id, payload);
    selectDocument(saved);
    return saved;
  }

  async function save(values) {
    return run(async () => {
      await persist(values);
      setMessage("보고서를 임시 저장했습니다. 정비 이력에서 다시 열 수 있습니다.");
    });
  }

  async function submit(values) {
    return run(async () => {
      const saved = await persist(values);
      const submitted = await actOnReport(saved.report_id, "submit", saved.revision);
      await refreshAfterAction(submitted);
      setMessage(user.role === lead ? "보고서를 제출했습니다. 관제 담당자의 최종 승인을 기다립니다." : "보고서를 제출했습니다. 보전 팀장의 검토를 기다립니다.");
    });
  }

  function open(id, version) {
    void run(async () => { selectDocument(await getReport(id, version)); });
  }

  function decide(action) {
    void run(async () => {
      const changed = await actOnReport(document.report_id, action, document.revision, comment);
      await refreshAfterAction(changed);
      setMessage(action === "approve"
        ? "최종 승인됐습니다. 검색 자료 등록 상태를 자동으로 확인합니다."
        : action === "revise" ? "수정할 보고서를 준비했습니다. 내용을 수정한 뒤 다시 제출해 주세요. 이전 버전과 결재 이력은 보존됩니다."
          : "결재 결과를 저장했습니다.");
    });
  }

  function removeReport(draft) {
    const text = draft
      ? document.report_version > 1
        ? "수정 중인 내용을 삭제하고 이전 반려 보고서로 돌아갈까요?"
        : "임시 저장한 보고서를 삭제할까요? 삭제한 내용은 복구할 수 없습니다."
      : "승인된 보고서와 모든 버전, 결재 이력 및 검색 자료를 삭제할까요? 삭제 후에는 복구할 수 없습니다.";
    if (!window.confirm(text)) return;
    void run(async () => {
      const result = await deleteReport(document.report_id, document.revision, draft);
      if (result.report) {
        await refreshAfterAction(result.report);
        setMessage("수정을 취소했습니다. 이전 반려 보고서가 유지됩니다.");
      } else {
        onNavigate("maintenance");
      }
    });
  }

  const own = !document || document.author_id === user.employee_no;
  const current = !document || document.current_version === document.report_version;
  const canWrite = [inspector, lead].includes(user.role);
  const editable = own && current && canWrite && (!document || document.report_status === "DRAFT");
  const reviewable = document && current && !own && (
    (user.role === lead && document.report_status === "SUBMITTED") ||
    (user.role === control && document.report_status === "REVIEWED")
  );
  const linkedIncident = document?.incident_id === incidentId ? document.incident : incidents.find((item) => item.incident_id === incidentId) ?? null;
  const availableIncidents = document?.incident && !incidents.some((item) => item.incident_id === document.incident_id)
    ? [document.incident, ...incidents] : incidents;

  return <section className="report-workspace">
    <header className="report-session">
      <p>{user.name} · {user.employee_no} · {user.role}</p>
    </header>
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {busy && <p role="status">저장·조회를 처리하고 있습니다.</p>}
    {(document || canWrite) && <>
      <section className="panel report-context">
        <h3>{document ? `${document.report_id} · v${document.report_version} · ${statuses[document.report_status]}` : "새 보고서 작성"}</h3>
        {editable && <div className="fields">
          <label>연결 사건<select value={incidentId} onChange={(event) => setIncidentId(event.target.value)} disabled={busy || Boolean(document?.incident_id)}>
            <option value="">사건을 선택해 주세요</option>
            {availableIncidents.map((item) => <option key={item.incident_id} value={item.incident_id}>{item.incident_id} · {item.asset_id} · {item.codes.join(", ")}</option>)}
          </select></label>
          <label>데이터 출처<select value={origin} onChange={(event) => setOrigin(event.target.value)} disabled={busy}>
            <option value="LIVE">실제 운전</option><option value="REPLAY">재생 데이터</option><option value="SYNTHETIC">가상 사례</option>
          </select></label>
        </div>}
        {editable && document?.incident_id && <p>보고서 번호와 연결된 사건은 저장 후 변경할 수 없습니다.</p>}
        {editable && availableIncidents.length === 0 && <p>DB에 저장된 사건이 없습니다. 보고서를 저장하려면 사건을 선택해야 합니다.</p>}
        {document && <>
          {!current && <p role="status">이전 버전입니다. 현재 버전은 v{document.current_version}이며, 이 버전은 조회만 할 수 있습니다.</p>}
          <p>작성자: {document.author_name} ({document.author_id}) · 마지막 처리: {new Date(document.updated_at).toLocaleString("ko-KR")}</p>
          <div className="report-actions">
            {Array.from({ length: document.current_version }, (_, index) => index + 1).map((version) => <button key={version} type="button" disabled={busy} onClick={() => open(document.report_id, version)}>v{version} 보기</button>)}
            <button type="button" disabled={busy} onClick={() => open(document.report_id)}>최신 내용 불러오기</button>
            {own && current && canWrite && document.report_status === "REJECTED" && <button type="button" className="report-revise-button" disabled={busy} onClick={() => decide("revise")}>보고서 수정하기</button>}
            {own && current && canWrite && document.report_status === "DRAFT" && <button type="button" className="report-delete-button" disabled={busy} onClick={() => removeReport(true)}>{document.report_version > 1 ? "수정 취소" : "임시 저장 삭제"}</button>}
            {current && user.role === control && document.report_status === "APPROVED" && <button type="button" className="report-delete-button" disabled={busy} onClick={() => removeReport(false)}>보고서 삭제</button>}
          </div>
          {document.approval.length > 0 && <section className="approval-history" aria-label="결재 이력">
            <h4>결재 이력</h4>
            <ol className="approval-history__list">
              {document.approval.map((item) => <li key={item.step} className={`approval-history__item${item.decision === "반려" ? " approval-history__item--rejected" : ""}`}>
                <div className="approval-history__heading">
                  <span className={`approval-history__badge approval-history__badge--${item.decision === "반려" ? "rejected" : item.decision === "승인" ? "approved" : "submitted"}`}>{item.decision}</span>
                  <span className="approval-history__person">{item.role} <span>· {item.user}</span></span>
                  <time dateTime={item.at}>{new Date(item.at).toLocaleString("ko-KR")}</time>
                </div>
                {item.comment && <div className="approval-history__comment">
                  <strong>{item.decision === "반려" ? "반려 사유" : "결재 의견"}</strong>
                  <p>{item.comment}</p>
                </div>}
              </li>)}
            </ol>
          </section>}
          {document.index_status === "pending" && <p>최종 승인된 보고서입니다. 검색 자료 등록 대기 중입니다.</p>}
          {document.index_status === "indexed" && <p>검색 자료 등록이 완료됐습니다.</p>}
          {document.index_status === "failed" && <p>검색 자료 등록에 실패했습니다. 관리자에게 재처리를 요청하세요.</p>}
        </>}
      </section>
      <ReportForm
        key={document ? `${document.report_id}:${document.report_version}:${document.revision}` : `new:${user.employee_no}`}
        incident={linkedIncident}
        analysis={document?.incident_id === incidentId ? document?.ai_analysis : null}
        reportId={document?.report_id}
        savedValues={formValues(document)}
        author={{ name: document?.author_name ?? user.name, employee_no: document?.author_id ?? user.employee_no }}
        statusLabel={document ? statuses[document.report_status] : "작성 중"}
        readOnly={!editable} busy={busy} onSave={save} onSubmit={submit}
      />
      {reviewable && <section className="panel">
        <h3>보고서 결재</h3>
        <label>결재 의견 — 반려 시 필수<textarea value={comment} onChange={(event) => setComment(event.target.value)} maxLength={2000} disabled={busy} /></label>
        <div className="report-actions">
          <button type="button" disabled={busy} onClick={() => decide(user.role === lead ? "review" : "approve")}>{user.role === lead ? "검토 승인" : "최종 승인"}</button>
          <button type="button" disabled={busy || !comment.trim()} onClick={() => decide("reject")}>반려</button>
        </div>
      </section>}
    </>}
  </section>;
}
