import { evidenceLabel } from "./evidenceLabels";
import { useEffect, useRef, useState } from "react";

import {
  analyzeTestIncident,
  approveTestReport,
  checkHealth,
  uploadDocument,
} from "../api/client";

import ManualListPage from "../pages/ManualListPage.jsx";
import ReportWorkspace from "./ReportWorkspace.jsx";
import { documentVersionFromFilename } from "./documentVersion.js";
import "../styles/workspace.scss";
import { canControl } from "./permissions";

const tabs = [
  { id: "documents", label: "문서 등록" },
  { id: "manual-list", label: "문서 목록" },
  { id: "report-write", label: "보고서·결재" },
  { id: "analysis", label: "에러 분석" },
];

const progressMessages = {
  uploading: "PDF를 업로드하고 있습니다.",
  queued: "처리 순서를 기다리고 있습니다.",
  parsing: "파싱 중입니다.",
  chunking: "청킹 중입니다.",
  loading_model: "임베딩 모델을 준비 중입니다.",
  embedding: "임베딩 중입니다.",
  storing: "벡터 DB에 저장 중입니다.",
  completed: "문서 등록이 완료됐습니다.",
};

const documentKinds = { manual: "매뉴얼", rule: "룰베이스", sop: "규정·SOP" };

function compareVersions(left, right) {
  if (!/^\d+(\.\d+)*$/.test(left) || !/^\d+(\.\d+)*$/.test(right)) return null;
  const a = left.split(".").map(BigInt);
  const b = right.split(".").map(BigInt);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if ((a[i] ?? 0n) !== (b[i] ?? 0n)) return (a[i] ?? 0n) > (b[i] ?? 0n) ? 1 : -1;
  }
  return 0;
}

function DocumentDialog({ replacement, completed, failure, onCancel, onConfirm }) {
  const dialog = useRef(null);
  const button = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    const focused = document.activeElement;
    element.showModal();
    button.current.focus();
    return () => { element.close(); focused?.focus(); };
  }, []);
  const current = replacement?.detail.current;
  const incoming = replacement?.detail.incoming;
  const order = current && compareVersions(incoming.doc_version, current.doc_version);
  return <dialog ref={dialog} className="document-dialog" aria-labelledby="document-dialog-title"
    onCancel={(event) => { event.preventDefault(); onCancel(); }}>
    {completed ? <>
      <h2 id="document-dialog-title">문서등록이 완료되었습니다</h2>
      <p>문서가 검색 자료로 등록되었습니다.</p>
      <div className="document-dialog__actions"><button ref={button} className="primary" type="button" onClick={onCancel}>확인</button></div>
    </> : failure ? <>
      <h2 id="document-dialog-title">{failure.title}</h2>
      <p>{failure.message}</p>
      <div className="document-dialog__actions"><button ref={button} className="primary" type="button" onClick={onCancel}>확인</button></div>
    </> : <>
      <h2 id="document-dialog-title">기존 문서를 교체할까요?</h2>
      <p>같은 문서 ID가 있습니다. 교체하면 기존 검색 자료도 새 문서로 바뀝니다.</p>
      <div className="document-dialog__details">
        <p><strong>기존</strong> {current.title} · {documentKinds[current.doc_type]} · v{current.doc_version}</p>
        <p><strong>새 문서</strong> {incoming.title} · {documentKinds[current.doc_type]} · v{incoming.doc_version}</p>
        <p>문서 ID: {current.doc_id} · 설비: {current.asset_id}</p>
      </div>
      {order !== null && order <= 0 && <p className="document-dialog__warning">새 문서 버전이 기존 버전과 같거나 낮습니다. 파일명을 확인해 주세요.</p>}
      <div className="document-dialog__actions">
        <button ref={button} type="button" onClick={onCancel}>취소</button>
        <button className="primary" type="button" onClick={onConfirm}>교체하여 등록</button>
      </div>
    </>}
  </dialog>;
}

function TextField({
  label,
  name,
  defaultValue = "",
  placeholder,
  required = true,
}) {
  return (
    <label>
      {label}
      <input
        name={name}
        defaultValue={defaultValue}
        placeholder={placeholder}
        required={required}
      />
    </label>
  );
}

function DocumentUploadFields() {
  const [version, setVersion] = useState("1.0");

  return (
    <>
      <label className="full-width">
        PDF 파일
        <input
          type="file"
          name="file"
          accept=".pdf,application/pdf"
          required
          onChange={(event) =>
            setVersion(documentVersionFromFilename(event.target.files?.[0]?.name ?? ""))
          }
        />
      </label>
      <TextField label="문서 ID" name="doc_id" placeholder="예: BLDC-001-MANUAL" />
      <div className="document-version">
        <label>
          문서 버전
          <input
            name="doc_version"
            value={version}
            readOnly
            aria-describedby="document-version-help"
          />
        </label>
        <small id="document-version-help">
          파일명에서 자동 설정됩니다. v1.0 같은 표기가 없으면 1.0을 사용합니다.
        </small>
      </div>
      <label>
        문서 종류
        <select name="doc_type" defaultValue="manual">
          <option value="manual">매뉴얼</option>
          <option value="sop">규정·SOP</option>
          <option value="rule">룰베이스</option>
        </select>
      </label>
      <TextField label="적용 설비 ID" name="asset_id" defaultValue="BLDC-001" />
    </>
  );
}

function TextArea({ label, name, placeholder, required = true }) {
  return (
    <label className="full-width">
      {label}
      <textarea
        name={name}
        rows={4}
        placeholder={placeholder}
        required={required}
      />
    </label>
  );
}

function ResultPanel({ result }) {
  const analysis = result?.analysis;
  const evidence = result?.evidence ?? analysis?.evidence ?? [];

  return (
    <section className="panel">
      <h2>실행 결과</h2>

      {result?.filters && (
        <p>적용된 검색 필터: {JSON.stringify(result.filters)}</p>
      )}

      {analysis && (
        <div className="result-block">
          <h3>AI 분석</h3>
          <p>상태: {analysis.status}</p>
          <p>{analysis.observed_facts}</p>

          {analysis.suspected_causes?.length > 0 && (
            <>
              <h4>원인 후보</h4>
              <ul>
                {analysis.suspected_causes.map((item, index) => (
                  <li key={index}>
                    {item.cause} — {item.basis}
                  </li>
                ))}
              </ul>
            </>
          )}

          {analysis.recommended_checks?.length > 0 && (
            <>
              <h4>점검 순서</h4>
              <ol>
                {analysis.recommended_checks.map((text, index) => (
                  <li key={index}>{text}</li>
                ))}
              </ol>
            </>
          )}

          {analysis.limitations && <p>{analysis.limitations}</p>}
        </div>
      )}

      {evidence.length > 0 && (
        <>
          <h3>검색된 근거</h3>
          {evidence.map((item, index) => (
            <article
              className="evidence"
              key={item.evidence_id ?? index}
            >
              <strong>
                {evidenceLabel(item)}
              </strong>
              {item.score != null && <p>점수: {item.score}</p>}
              <p className="preserve-lines">{item.text}</p>
            </article>
          ))}
        </>
      )}

      <details open={!analysis && evidence.length === 0}>
        <summary>전체 서버 응답</summary>
        <pre>{JSON.stringify(result, null, 2)}</pre>
      </details>
    </section>
  );
}

export default function RagWorkspace({ tab, user, onSessionExpired, onBusyChange, workspaceBusy, onNavigate, reportSelection }) {
  const canManageManuals = canControl(user);
  const registrationRestricted = tab === "documents" && !canManageManuals;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [replacement, setReplacement] = useState(null);
  const [documentFailure, setDocumentFailure] = useState(null);
  const [completed, setCompleted] = useState(() => Boolean(sessionStorage.getItem("weeing-document-completed")));
  const [progressMessage, setProgressMessage] = useState(
    "서버에서 처리 중입니다…",
  );

  async function execute(action) {
    setBusy(true);
    onBusyChange(true);
    setError("");
    setResult(null);
    setProgressMessage("서버에서 처리 중입니다…");

    try {
      setResult({ page: tab, value: await action() });
    } catch (requestError) {
      if (requestError.status === 401) onSessionExpired();
      setError({ page: tab, message: requestError.message });
    } finally {
      setBusy(false);
      onBusyChange(false);
    }
  }

  async function registerDocument(form) {
    setBusy(true);
    onBusyChange(true);
    setError("");
    setResult(null);
    setDocumentFailure(null);
    try {
      await uploadDocument(form, (stage) => setProgressMessage(progressMessages[stage] ?? "처리 상태를 확인하고 있습니다…"));
      sessionStorage.setItem("weeing-document-completed", "1");
      window.location.reload();
    } catch (failure) {
      if (failure.status === 401) {
        onSessionExpired();
      } else if (failure.status === 409 && failure.detail?.code === "replace_confirmation_required") {
        setReplacement({ form, detail: failure.detail });
      } else {
        setDocumentFailure({
          title: failure.status ? "문서를 등록할 수 없습니다" : "문서 등록 상태를 확인해 주세요",
          message: typeof failure.detail === "string" ? failure.detail : failure.message,
        });
      }
    } finally {
      setBusy(false);
      onBusyChange(false);
    }
  }

  function confirmReplacement() {
    const { form, detail } = replacement;
    form.set("confirm_replace", "true");
    form.set("expected_upload_id", detail.current.upload_id ?? "");
    form.set("expected_version", detail.current.doc_version);
    form.set("expected_sha256", detail.current.source_sha256);
    setReplacement(null);
    void registerDocument(form);
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (busy) return;

    const form = new FormData(event.currentTarget);
    const value = (name) => String(form.get(name) ?? "").trim();

    if (tab === "documents") {
      if (!canManageManuals) return;
      void registerDocument(form);
      return;
    }

    const codes = value("codes")
      .split(/[,\s]+/)
      .filter(Boolean);

    if (tab === "reports") {
      const payload = {
        report_id: value("report_id"),
        incident_id: value("incident_id"),
        asset_id: value("asset_id"),
        codes,
        confirmed_cause: value("confirmed_cause"),
        actions_taken: value("actions_taken")
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
        data_origin: "SYNTHETIC",
      };

      void execute(() => approveTestReport(payload));
      return;
    }

    const payload = {
      asset_id: value("asset_id"),
      codes,
      symptom: value("symptom"),
    };

    void execute(() => analyzeTestIncident(payload));
  }

  return (
    <div className="rag-workspace">
      {completed && <DocumentDialog completed onCancel={() => { sessionStorage.removeItem("weeing-document-completed"); setCompleted(false); }} />}
      {replacement && <DocumentDialog replacement={replacement} onCancel={() => setReplacement(null)} onConfirm={confirmReplacement} />}
      {documentFailure && <DocumentDialog failure={documentFailure} onCancel={() => setDocumentFailure(null)} />}
      <header className="page-header">
        <div>
          <div className="eyebrow">WORKSPACE</div>
          <h1>{tabs.find((item) => item.id === tab)?.label}</h1>
          {tab === "manual-list" && <p>등록된 문서와 검색 자료의 상태를 확인하세요.</p>}
          {tab === "documents" && <p>PDF 문서를 등록해 검색과 분석의 근거로 활용하세요.</p>}
        </div>

        {tab !== "manual-list" && tab !== "report-write" && !registrationRestricted && <button
          type="button"
          disabled={workspaceBusy}
          onClick={() => void execute(checkHealth)}
        >
          서버 연결 확인
        </button>}
      </header>

      <div hidden={tab !== "report-write"}>
        <ReportWorkspace active={tab === "report-write"} key={reportSelection.key} initialDocument={reportSelection.document} initialIncidentId={reportSelection.incidentId} initialIncident={reportSelection.incident} initialTelemetry={reportSelection.telemetry} initialAnalysis={reportSelection.analysis} onNavigate={onNavigate} user={user} onSessionExpired={onSessionExpired} onBusyChange={onBusyChange} />
      </div>

      {tab === "manual-list" && <ManualListPage user={user} onSessionExpired={onSessionExpired}
        onBusyChange={onBusyChange} onNavigate={onNavigate} />}

      {registrationRestricted && <section className="panel document-access" aria-labelledby="document-access-title">
        <div className="document-access__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <rect x="5" y="10" width="14" height="11" rx="2" />
            <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" />
          </svg>
        </div>
        <h2 id="document-access-title">문서 등록은 관제 담당자만 가능합니다</h2>
        <p>등록된 문서는 문서 목록에서 확인할 수 있습니다.</p>
        <button className="primary" type="button" disabled={workspaceBusy} onClick={() => onNavigate("manual-list")}>문서 목록 보기 →</button>
      </section>}

      {!registrationRestricted && <section className="panel" hidden={tab === "report-write" || tab === "manual-list"}>
        <h2>{tabs.find((item) => item.id === tab)?.label}</h2>

        {tab === "reports" && (
          <p>
            가상 보고서를 승인된 이력으로 등록하는 테스트입니다.
            실제 결재 화면은 별도로 연결합니다.
          </p>
        )}

        {tab === "analysis" && (
          <p>
            설비와 에러 정보를 직접 입력해서 검색·분석을 실행합니다.
          </p>
        )}

        <form key={tab} onSubmit={handleSubmit}>
          <fieldset disabled={workspaceBusy}>
            <div className="fields">
              {tab === "documents" && <DocumentUploadFields />}

              {tab === "reports" && (
                <>
                  <TextField
                    label="테스트 보고서 ID"
                    name="report_id"
                    defaultValue="TEST-RPT-001"
                  />
                  <TextField
                    label="테스트 사건 ID"
                    name="incident_id"
                    defaultValue="TEST-INC-001"
                  />
                  <TextField
                    label="설비 ID"
                    name="asset_id"
                    defaultValue="BLDC-001"
                  />
                  <TextField
                    label="에러 코드 — 여러 개는 쉼표로 구분"
                    name="codes"
                    defaultValue="BTT2-P01"
                  />
                  <TextArea
                    label="사람이 확인한 원인"
                    name="confirmed_cause"
                    placeholder="테스트용으로 확인한 원인을 입력하세요."
                  />
                  <TextArea
                    label="실제 수행한 조치 — 한 줄에 하나"
                    name="actions_taken"
                    placeholder="테스트용으로 수행한 조치를 입력하세요."
                  />
                </>
              )}

              {tab === "analysis" && (
                <>
                  <TextField
                    label="설비 ID"
                    name="asset_id"
                    defaultValue="BLDC-001"
                  />
                  <TextField
                    label="에러 코드 — 여러 개는 쉼표로 구분"
                    name="codes"
                    defaultValue="BTT2-P01"
                  />
                  <TextArea
                    label="관측 증상·주요 측정값"
                    name="symptom"
                    placeholder="예: 트레이가 출구에 도착하지 않음. RPM은 정상 범위."
                  />
                </>
              )}
            </div>

            {(tab !== "documents" || canManageManuals) && <button className="primary" type="submit">
              {tab === "documents"
                ? "문서 등록 실행"
                : tab === "reports"
                  ? "가상 보고서 승인·등록"
                  : "검색·분석 실행"}
            </button>}
          </fieldset>
        </form>
      </section>}

      {busy && <p role="status">{progressMessage}</p>}
      {!registrationRestricted && error?.page === tab && <p className="error" role="alert">{error.message}</p>}
      {!registrationRestricted && result?.page === tab && tab === "documents" && result.value?.status === "completed"
        ? <div className="panel"><h2>문서 등록이 완료됐습니다</h2>
            <p>{result.value.title} · {result.value.chunk_count}개 검색 자료가 등록됐습니다.</p>
            <button type="button" onClick={() => onNavigate("manual-list")}>문서 목록 보기</button>
          </div>
        : !registrationRestricted && result?.page === tab && <ResultPanel result={result.value} />}
    </div>
  );
}
