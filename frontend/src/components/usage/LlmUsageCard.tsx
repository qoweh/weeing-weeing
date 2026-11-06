import { useEffect, useState } from "react";
import {
  getLlmUsage,
  type LlmUsagePeriod,
  type LlmUsagePoint,
  type LlmUsageSummary,
} from "../../api/client";
import Glyph from "../ui/Glyph";

// LLM 사용량 요약(#207). 계정 관리자·관제 담당자만 본다(access.ts).
// 자세한 분석은 헤더 오른쪽 Langfuse 대시보드 링크로 넘긴다.
const periods: { value: LlmUsagePeriod; label: string }[] = [
  { value: "1h", label: "1시간" },
  { value: "24h", label: "24시간" },
  { value: "7d", label: "7일" },
  { value: "30d", label: "30일" },
  { value: "all", label: "누적" },
];

type Measure = "calls" | "tokens" | "cost_usd";
const measures: { value: Measure; label: string }[] = [
  { value: "calls", label: "호출" },
  { value: "tokens", label: "토큰" },
  { value: "cost_usd", label: "비용" },
];

const numberFormat = new Intl.NumberFormat("ko-KR");
const compactFormat = new Intl.NumberFormat("ko-KR", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const costFormat = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

function formatMeasure(measure: Measure, value: number) {
  if (measure === "cost_usd") return costFormat.format(value);
  if (measure === "tokens") return `${numberFormat.format(value)} 토큰`;
  return `${numberFormat.format(value)}회`;
}

function formatTime(iso: string, granularity: LlmUsageSummary["granularity"]) {
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  const md = `${date.getMonth() + 1}/${date.getDate()}`;
  if (granularity === "minute")
    return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (granularity === "hour") return `${md} ${pad(date.getHours())}시`;
  if (granularity === "day") return md;
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}`;
}

export default function LlmUsageCard({
  onSessionExpired,
}: {
  onSessionExpired: () => void;
}) {
  const [period, setPeriod] = useState<LlmUsagePeriod>("7d");
  const [measure, setMeasure] = useState<Measure>("calls");
  const [data, setData] = useState<LlmUsageSummary | null>(null);
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    getLlmUsage(period)
      .then((summary) => {
        if (active) setData(summary);
      })
      .catch((failure) => {
        if (!active) return;
        if (failure.status === 401) onSessionExpired();
        else if (failure.status === 403) setForbidden(true);
        else setError(failure.message);
      });
    return () => {
      active = false;
    };
  }, [period, onSessionExpired]);

  // 서버 규칙이 최종 판단이다. 권한이 없다고 하면 카드를 숨긴다.
  if (forbidden) return null;

  const failed = error || (data && data.status !== "ok" ? data.message : "");
  const dashboardUrl = (data?.dashboard_url || "").startsWith("http")
    ? data!.dashboard_url
    : "";

  return (
    <section className="mypage__card mypage__usage" aria-label="LLM 사용량">
      <div className="mypage__usage-head">
        <h2>LLM 사용량</h2>
        <div className="mypage__usage-tools">
          <div
            className="mypage__usage-periods"
            role="group"
            aria-label="기간"
          >
            {periods.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={period === item.value}
                onClick={() => setPeriod(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
          {dashboardUrl && (
            <a
              className="mypage__link mypage__usage-dashboard"
              href={dashboardUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              Langfuse 대시보드에서 자세히 보기{" "}
              <span aria-hidden="true">
                <Glyph name="arrow-right" />
              </span>
            </a>
          )}
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
              <strong>{numberFormat.format(data.total_tokens)}</strong>
              <small className="mypage__usage-sub">
                입력 {compactFormat.format(data.input_tokens)} · 출력{" "}
                {compactFormat.format(data.output_tokens)}
              </small>
            </div>
            <div>
              <span className="mypage__summary-label">비용</span>
              <strong>{costFormat.format(data.total_cost_usd)}</strong>
              <small className="mypage__usage-sub">USD, Langfuse 단가 기준</small>
            </div>
            <div>
              <span className="mypage__summary-label">LLM 호출</span>
              <strong>
                {numberFormat.format(data.calls)}
                <small>회</small>
              </strong>
              <small className="mypage__usage-sub">
                모델 {data.models.length}개
              </small>
            </div>
          </div>
          {data.calls === 0 ? (
            <p className="mypage__empty mypage__usage-empty">
              이 기간에는 LLM 호출 기록이 없습니다.
            </p>
          ) : (
            <>
              <UsageTrend
                series={data.series}
                granularity={data.granularity}
                measure={measure}
                onMeasure={setMeasure}
              />
              <ModelTable data={data} />
            </>
          )}
        </>
      )}
    </section>
  );
}

function UsageTrend({
  series,
  granularity,
  measure,
  onMeasure,
}: {
  series: LlmUsagePoint[];
  granularity: LlmUsageSummary["granularity"];
  measure: Measure;
  onMeasure: (measure: Measure) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(0, ...series.map((point) => point[measure]));
  const label = measures.find((item) => item.value === measure)!.label;
  const active = hover === null ? null : series[hover];
  const ticks =
    series.length > 2
      ? [0, Math.floor((series.length - 1) / 2), series.length - 1]
      : series.map((_, index) => index);

  return (
    <div className="mypage__usage-trend">
      <div className="mypage__usage-trend-head">
        <h3>기간 내 추이</h3>
        <div
          className="mypage__usage-periods mypage__usage-measures"
          role="group"
          aria-label="추이 기준"
        >
          {measures.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={measure === item.value}
              onClick={() => onMeasure(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      <p className="mypage__usage-readout" aria-live="polite">
        {active
          ? `${formatTime(active.time, granularity)} · ${formatMeasure(measure, active[measure])}`
          : `최대 ${formatMeasure(measure, max)}`}
      </p>
      <div
        className="mypage__usage-bars"
        role="img"
        aria-label={`${label} 추이, 막대 ${series.length}개, 최대 ${formatMeasure(measure, max)}`}
        onMouseLeave={() => setHover(null)}
      >
        {series.map((point, index) => {
          const value = point[measure];
          const height = max > 0 ? (value / max) * 100 : 0;
          return (
            <div
              key={point.time}
              className="mypage__usage-bar"
              data-active={hover === index || undefined}
              onMouseEnter={() => setHover(index)}
            >
              <span
                style={{
                  height: value > 0 ? `max(${height}%, 2px)` : "0",
                }}
              />
            </div>
          );
        })}
      </div>
      <div className="mypage__usage-axis" aria-hidden="true">
        {ticks.map((index) => (
          <span key={index}>
            {formatTime(series[index].time, granularity)}
          </span>
        ))}
      </div>
    </div>
  );
}

function ModelTable({ data }: { data: LlmUsageSummary }) {
  const total = data.total_cost_usd;
  return (
    <div className="mypage__usage-table-wrap">
      <table className="mypage__usage-table">
        <caption>모델별 사용량 (비용 순)</caption>
        <thead>
          <tr>
            <th scope="col">모델</th>
            <th scope="col">호출</th>
            <th scope="col">입력 토큰</th>
            <th scope="col">출력 토큰</th>
            <th scope="col">토큰 합계</th>
            <th scope="col">비용</th>
            <th scope="col">비용 비중</th>
          </tr>
        </thead>
        <tbody>
          {data.models.map((model) => {
            const share = total > 0 ? (model.cost_usd / total) * 100 : 0;
            return (
              <tr key={model.model}>
                <th scope="row">{model.model}</th>
                <td>{numberFormat.format(model.calls)}</td>
                <td>{numberFormat.format(model.input_tokens)}</td>
                <td>{numberFormat.format(model.output_tokens)}</td>
                <td>{numberFormat.format(model.tokens)}</td>
                <td>{costFormat.format(model.cost_usd)}</td>
                <td>
                  <span className="mypage__usage-share">
                    <span className="mypage__usage-share-track">
                      <span style={{ width: `${share}%` }} />
                    </span>
                    {share.toFixed(1)}%
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
