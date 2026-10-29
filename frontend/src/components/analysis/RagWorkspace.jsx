import { useState } from "react";

import {
  analyzeTestIncident,
  approveTestReport,
  checkHealth,
  uploadDocument,
} from "../../api/client";

import ReportWorkspace from "../report/ReportWorkspace.jsx";
import "../../styles/workspace.scss";

const tabs = [
  { id: "documents", label: "문서 등록" },
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
                {item.citation ?? item.doc_id ?? `근거 ${index + 1}`}
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

export default function RagWorkspace({ tab, user, onSessionExpired, onBusyChange, workspaceBusy }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
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

  function handleSubmit(event) {
    event.preventDefault();
    if (busy) return;

    const form = new FormData(event.currentTarget);
    const value = (name) => String(form.get(name) ?? "").trim();

    if (tab === "documents") {
      void execute(() =>
        uploadDocument(form, (stage) => {
          setProgressMessage(
            progressMessages[stage] ?? "처리 상태를 확인하고 있습니다…",
          );
        }),
      );
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
      <header className="page-header">
        <div>
          <div className="eyebrow">WORKSPACE</div>
          <h1>{tabs.find((item) => item.id === tab)?.label}</h1>
          <p>문서 등록과 보고서·결재, 검색·분석을 관리하세요.</p>
        </div>

        <button
          type="button"
          disabled={workspaceBusy}
          onClick={() => void execute(checkHealth)}
        >
          서버 연결 확인
        </button>
      </header>

      <div hidden={tab !== "report-write"}>
        <ReportWorkspace user={user} onSessionExpired={onSessionExpired} onBusyChange={onBusyChange} />
      </div>

      <section className="panel" hidden={tab === "report-write"}>
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
              {tab === "documents" && (
                <>
                  <label className="full-width">
                    PDF 파일
                    <input
                      type="file"
                      name="file"
                      accept=".pdf,application/pdf"
                      required
                    />
                  </label>

                  <TextField
                    label="문서 ID"
                    name="doc_id"
                    placeholder="예: BLDC-001-MANUAL (카탈로그 문서 ID는 쓸 수 없음)"
                  />
                  <TextField
                    label="문서 버전"
                    name="doc_version"
                    defaultValue="1.0"
                  />

                  <label>
                    문서 종류
                    <select name="doc_type" defaultValue="manual">
                      <option value="manual">매뉴얼</option>
                      <option value="sop">규정·SOP</option>
                      <option value="rule">룰베이스</option>
                    </select>
                  </label>

                  <TextField
                    label="적용 설비 ID"
                    name="asset_id"
                    defaultValue="BLDC-001"
                  />
                </>
              )}

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

            <button className="primary" type="submit">
              {tab === "documents"
                ? "문서 등록 실행"
                : tab === "reports"
                  ? "가상 보고서 승인·등록"
                  : "검색·분석 실행"}
            </button>
          </fieldset>
        </form>
      </section>

      {busy && <p role="status">{progressMessage}</p>}
      {error?.page === tab && <p className="error" role="alert">{error.message}</p>}
      {result?.page === tab && <ResultPanel result={result.value} />}
    </div>
  );
}
