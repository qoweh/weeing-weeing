import { useEffect, useState } from "react";
import { getLlmUsage, type LlmUsageSummary } from "../../api/client";
import Glyph from "../ui/Glyph";

// 관리자 전용 LLM 사용량 요약(#207). 자세한 분석은 Langfuse 대시보드 링크로 넘긴다.
const periods = [
  { days: 1, label: "24시간" },
  { days: 7, label: "7일" },
  { days: 30, label: "30일" },
];

const tokenFormat = new Intl.NumberFormat("ko-KR");
const costFormat = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

export default function LlmUsageCard({
  onSessionExpired,
}: {
  onSessionExpired: () => void;
}) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<LlmUsageSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    getLlmUsage(days)
      .then((summary) => {
        if (active) setData(summary);
      })
      .catch((failure) => {
        if (!active) return;
        if (failure.status === 401) onSessionExpired();
        else setError(failure.message);
      });
    return () => {
      active = false;
    };
  }, [days, onSessionExpired]);

  const failed = error || (data && data.status !== "ok" ? data.message : "");

  return (
    <section className="mypage__card mypage__usage" aria-label="LLM 사용량">
      <div className="mypage__usage-head">
        <h2>LLM 사용량</h2>
        <div className="mypage__usage-periods" role="group" aria-label="기간">
          {periods.map((period) => (
            <button
              key={period.days}
              type="button"
              aria-pressed={days === period.days}
              onClick={() => setDays(period.days)}
            >
              {period.label}
            </button>
          ))}
        </div>
      </div>
      {failed ? (
        <p role="alert" className="mypage__empty">
          조회 실패: {failed}
        </p>
      ) : !data ? (
        <p role="status" className="mypage__loading">
          사용량을 불러오는 중입니다.
        </p>
      ) : (
        <>
          <div className="mypage__summary mypage__usage-summary">
            <div>
              <span className="mypage__summary-label">토큰</span>
              <strong>{tokenFormat.format(data.total_tokens)}</strong>
            </div>
            <div>
              <span className="mypage__summary-label">비용</span>
              <strong>{costFormat.format(data.total_cost_usd)}</strong>
            </div>
            <div>
              <span className="mypage__summary-label">LLM 호출</span>
              <strong>
                {tokenFormat.format(data.calls)}
                <small>회</small>
              </strong>
            </div>
          </div>
          {data.models.length > 0 && (
            <ul className="mypage__list mypage__usage-models">
              {data.models.slice(0, 5).map((model) => (
                <li key={model.model}>
                  <span>
                    <strong>{model.model}</strong>
                    <small>
                      {tokenFormat.format(model.tokens)} 토큰 · {model.calls}회
                    </small>
                  </span>
                  <span>{costFormat.format(model.cost_usd)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {(data?.dashboard_url || "").startsWith("http") && (
        <a
          className="mypage__link"
          href={data!.dashboard_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Langfuse 대시보드에서 자세히 보기{" "}
          <span aria-hidden="true">
            <Glyph name="arrow-right" />
          </span>
        </a>
      )}
    </section>
  );
}
