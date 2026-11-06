import ChatMarkdown from "./ChatMarkdown.js";

const labels = {
  NEEDS_CLARIFICATION: "추가 확인",
  INSUFFICIENT_EVIDENCE: "근거 부족",
  OUT_OF_SCOPE: "지원 범위 밖",
  FAILED: "처리 실패",
};
const failureHelp = {
  LLM_AUTHENTICATION: "서버의 AI 인증 설정을 확인해 주세요.",
  RATE_LIMITED: "호출 한도에 도달했습니다. 잠시 후 다시 이용해 주세요.",
  TIMEOUT: "답변 처리 시간이 초과됐습니다.",
  SEARCH_UNAVAILABLE: "자료 검색 서비스를 이용할 수 없습니다.",
  STORAGE_UNAVAILABLE: "대화 저장 서비스를 이용할 수 없습니다.",
  ACCESS_DENIED: "이 대화에 접근할 수 없습니다.",
};

function sourceKey(source) {
  if (source.kind === "DOCUMENT")
    return `doc:${source.doc_id}:${source.doc_version}:${source.page ?? source.section}`;
  if (source.kind === "REPORT")
    return `report:${source.report_id}:${source.report_version}`;
  return source.source_id;
}
export default function ChatResponse({ response, onSource }) {
  const sources = [
    ...new Map(
      (response.sources || []).map((source) => [sourceKey(source), source]),
    ).values(),
  ];
  return (
    <>
      {labels[response.status] && (
        <span
          className={`chat-status chat-status--${response.status.toLowerCase()}`}
        >
          {labels[response.status]}
        </span>
      )}
      {response.status === "OK" && response.parts?.length ? (
        response.parts.map((part, i) => (
          <ChatMarkdown key={i}>{part.text}</ChatMarkdown>
        ))
      ) : (
        <ChatMarkdown>{response.message}</ChatMarkdown>
      )}
      {response.clarification_questions?.length > 0 && (
        <ul>
          {response.clarification_questions.map((question, i) => (
            <li key={i}>{question}</li>
          ))}
        </ul>
      )}
      {response.failure && (
        <p>
          {failureHelp[response.failure.code] ||
            "요청을 처리하지 못했습니다. 서버 상태를 확인해 주세요."}
        </p>
      )}
      {sources.length > 0 && (
        <div className="chat-sources" aria-label="답변 출처">
          <strong>출처</strong>
          {sources.map((source) => (
            <div key={sourceKey(source)}>
              {["DOCUMENT", "REPORT"].includes(source.kind) ? (
                <button type="button" onClick={() => onSource(source)}>
                  {source.title}
                  <span>
                    {source.kind === "DOCUMENT"
                      ? `${source.doc_id} v${source.doc_version} · ${source.page ? `${source.page}쪽` : source.section}`
                      : `${source.report_id} v${source.report_version}`}
                  </span>
                </button>
              ) : (
                <span>
                  {source.title}
                  {source.kind === "INCIDENT_QUERY" &&
                    ` · 주의 ${source.warning_count}건 / 경고 ${source.error_count}건 · 조회 ${source.retrieved_at}`}
                  {source.kind === "HISTORY_QUERY"
                    ? ` · 보고서 ${source.total}건`
                    : ""}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
