import { useEffect, useState } from "react";

import {
  actOnReport, currentUser, getReport, listIncidents, listReports, loginUser,
  logoutUser, saveReport, setAccessToken,
} from "../api/client";
import ReportForm from "./ReportForm";
import { draftValues, formValues } from "./reportValues";
import "./ReportWorkspace.css";

const sessionKey = "weeing-report-session";
const statuses = { DRAFT: "작성 중", SUBMITTED: "제출됨", REVIEWED: "검토 승인", APPROVED: "최종 승인", REJECTED: "반려" };
const inspector = "현장 점검자";
const lead = "보전 팀장";
const control = "관제 담당자";

export default function ReportWorkspace() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(() => Boolean(sessionStorage.getItem(sessionKey)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [mine, setMine] = useState([]);
  const [queue, setQueue] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [document, setDocument] = useState(null);
  const [incidentId, setIncidentId] = useState("");
  const [origin, setOrigin] = useState("LIVE");
  const [comment, setComment] = useState("");
  const [reload, setReload] = useState(0);
  const [newReport, setNewReport] = useState(0);

  function forgetSession() {
    setAccessToken("");
    sessionStorage.removeItem(sessionKey);
    setUser(null);
    setDocument(null);
    setMine([]);
    setQueue([]);
    setIncidents([]);
    setComment("");
    setIncidentId("");
    setOrigin("LIVE");
  }

  useEffect(() => {
    const token = sessionStorage.getItem(sessionKey);
    if (!token) return;
    let cancelled = false;
    setAccessToken(token);
    currentUser().then((account) => {
      if (!cancelled) setUser(account);
    }).catch((failure) => {
      if (cancelled) return;
      if (failure.status === 401) {
        setAccessToken("");
        sessionStorage.removeItem(sessionKey);
      }
      setError(failure.message);
    }).finally(() => { if (!cancelled) setChecking(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const canReview = [lead, control].includes(user.role);
    Promise.all([listReports(), canReview ? listReports("review") : Promise.resolve([]), listIncidents()])
      .then(([ownReports, pending, available]) => {
        if (cancelled) return;
        setMine(ownReports);
        setQueue(pending);
        setIncidents(available);
      }).catch((failure) => {
        if (cancelled) return;
        setError(failure.message);
        if (failure.status === 401) {
          setAccessToken("");
          sessionStorage.removeItem(sessionKey);
          setUser(null);
          setDocument(null);
        }
      });
    return () => { cancelled = true; };
  }, [user, reload]);

  async function run(operation) {
    if (busy) return null;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      return await operation();
    } catch (failure) {
      if (failure.status === 401) forgetSession();
      setError(failure.message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  function selectDocument(value) {
    setDocument(value);
    setIncidentId(value?.incident_id ?? "");
    setOrigin(value?.data_origin ?? "LIVE");
    setComment("");
  }

  async function signIn(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await run(async () => {
      const session = await loginUser(String(data.get("employee_no")), String(data.get("password")));
      setAccessToken(session.access_token);
      sessionStorage.setItem(sessionKey, session.access_token);
      setUser(session.user);
      form.reset();
    });
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
    setReload((value) => value + 1);
    return saved;
  }

  async function save(values) {
    return run(async () => {
      await persist(values);
      setMessage("보고서를 임시 저장했습니다. 새로고침 후에도 ‘내가 쓴 보고서’에서 열 수 있습니다.");
    });
  }

  async function submit(values) {
    return run(async () => {
      const saved = await persist(values);
      const submitted = await actOnReport(saved.report_id, "submit", saved.revision);
      selectDocument(submitted);
      setReload((value) => value + 1);
      setMessage("보고서를 제출했습니다. 보전 팀장의 검토를 기다립니다.");
    });
  }

  function open(id, version) {
    void run(async () => { selectDocument(await getReport(id, version)); });
  }

  function decide(action) {
    void run(async () => {
      const changed = await actOnReport(document.report_id, action, document.revision, comment);
      selectDocument(changed);
      setReload((value) => value + 1);
      setMessage(action === "approve"
        ? "최종 승인됐습니다. 검색 자료 등록은 대기 중입니다."
        : action === "revise" ? "새 개정판을 만들었습니다. 이전 버전과 결재 이력은 보존됩니다."
          : "결재 결과를 저장했습니다.");
    });
  }

  if (checking) return <p role="status">로그인 상태를 확인하고 있습니다.</p>;

  if (!user) return (
    <section className="panel report-login">
      <h2>보고서 로그인</h2>
      <p>등록된 사번으로 로그인하면 내 보고서와 직책에 맞는 결재 대기 목록을 볼 수 있습니다.</p>
      <form onSubmit={signIn}>
        <label>사번<input name="employee_no" autoComplete="username" required /></label>
        <label>비밀번호<input name="password" type="password" autoComplete="current-password" required /></label>
        <button type="submit" disabled={busy}>로그인</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );

  const own = !document || document.author_id === user.employee_no;
  const current = !document || document.current_version === document.report_version;
  const editable = own && current && user.role === inspector && (!document || document.report_status === "DRAFT");
  const reviewable = document && current && !own && (
    (user.role === lead && document.report_status === "SUBMITTED") ||
    (user.role === control && document.report_status === "REVIEWED")
  );
  const linkedIncident = document?.incident_id === incidentId ? document.incident : incidents.find((item) => item.incident_id === incidentId) ?? null;
  const availableIncidents = document?.incident && !incidents.some((item) => item.incident_id === document.incident_id)
    ? [document.incident, ...incidents] : incidents;

  function reportList(title, items) {
    return <section className="panel report-list"><h3>{title}</h3>
      {items.length === 0 ? <p>표시할 보고서가 없습니다.</p> : <ul>{items.map((item) => (
        <li key={item.report_id}>
          <button type="button" disabled={busy} onClick={() => open(item.report_id)}>
            {item.report_id} · {statuses[item.report_status]} · v{item.report_version}
          </button>
          <span>{item.author_name} · {item.asset_id ?? "사건 미연결"}</span>
        </li>
      ))}</ul>}
    </section>;
  }

  return <section className="report-workspace">
    <header className="report-session">
      <p>{user.name} · {user.employee_no} · {user.role}</p>
      <button type="button" disabled={busy} onClick={() => void run(async () => { await logoutUser(); forgetSession(); })}>로그아웃</button>
      <button type="button" disabled={busy} onClick={() => setReload((value) => value + 1)}>목록 새로고침</button>
      {user.role === inspector && <button type="button" disabled={busy} onClick={() => { selectDocument(null); setNewReport((value) => value + 1); }}>새 보고서</button>}
    </header>
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {busy && <p role="status">저장·조회를 처리하고 있습니다.</p>}
    <div className="report-lists">
      {reportList("내가 쓴 보고서", mine)}
      {[lead, control].includes(user.role) && reportList("내 결재 대기", queue)}
    </div>
    {(document || user.role === inspector) && <>
      <section className="panel report-context">
        <h3>{document ? `${document.report_id} · v${document.report_version} · ${statuses[document.report_status]}` : "새 보고서 작성"}</h3>
        {editable && <div className="fields">
          <label>연결 사건<select value={incidentId} onChange={(event) => setIncidentId(event.target.value)} disabled={busy}>
            <option value="">선택하지 않음 — 임시 저장만 가능</option>
            {availableIncidents.map((item) => <option key={item.incident_id} value={item.incident_id}>{item.incident_id} · {item.asset_id} · {item.codes.join(", ")}</option>)}
          </select></label>
          <label>데이터 출처<select value={origin} onChange={(event) => setOrigin(event.target.value)} disabled={busy}>
            <option value="LIVE">실제 운전</option><option value="REPLAY">재생 데이터</option><option value="SYNTHETIC">가상 사례</option>
          </select></label>
        </div>}
        {editable && availableIncidents.length === 0 && <p>DB에 저장된 사건이 없습니다. 지금은 초안을 저장할 수 있고, 제출하려면 사건을 연결해야 합니다.</p>}
        {document && <>
          <p>작성자: {document.author_name} ({document.author_id}) · 마지막 처리: {new Date(document.updated_at).toLocaleString("ko-KR")}</p>
          <div className="report-actions">
            {Array.from({ length: document.current_version }, (_, index) => index + 1).map((version) => <button key={version} type="button" disabled={busy} onClick={() => open(document.report_id, version)}>v{version} 보기</button>)}
            <button type="button" disabled={busy} onClick={() => open(document.report_id)}>최신 내용 불러오기</button>
            {own && current && user.role === inspector && ["APPROVED", "REJECTED"].includes(document.report_status) && <button type="button" disabled={busy} onClick={() => decide("revise")}>개정판 작성</button>}
          </div>
          {document.approval.length > 0 && <ol>{document.approval.map((item) => <li key={item.step}>{item.role} · {item.user} · {item.decision} · {new Date(item.at).toLocaleString("ko-KR")} {item.comment && `— ${item.comment}`}</li>)}</ol>}
          {document.index_status === "pending" && <p>최종 승인된 보고서입니다. 검색 자료 등록 대기 중입니다.</p>}
        </>}
      </section>
      <ReportForm
        key={document ? `${document.report_id}:${document.report_version}:${document.revision}` : `new:${user.employee_no}:${newReport}`}
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
