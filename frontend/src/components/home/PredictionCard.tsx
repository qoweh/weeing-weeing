import type { MlSnapshot } from "../../api/client";
import type { Slice } from "./useHomeData";
import Glyph from "../ui/Glyph";
import HomeCard, { HomeBadge, HomeNotice, type HomeTone } from "./HomeCard";
import {
  percent,
  predictionNotice,
  probabilityTone,
  topPredictions,
} from "../dashboard/DashboardAside";

const defaultThreshold = 0.6;

export function predictionView(ml: Slice<MlSnapshot>) {
  const notice = predictionNotice(ml.data, ml.error !== "");
  const prediction = notice ? null : (ml.data?.prediction ?? null);
  const probability = prediction?.error_probability;
  const threshold =
    typeof prediction?.warning_threshold === "number"
      ? prediction.warning_threshold
      : defaultThreshold;
  return {
    notice,
    prediction,
    probability: typeof probability === "number" ? probability : null,
    threshold,
  };
}

const tones: Record<string, { tone: HomeTone; label: string }> = {
  danger: { tone: "danger", label: "경고 예측" },
  orange: { tone: "warning", label: "주의 예측" },
  normal: { tone: "success", label: "정상 범위" },
};

export default function PredictionCard({ ml }: { ml: Slice<MlSnapshot> }) {
  const { notice, prediction, probability, threshold } = predictionView(ml);
  const rows = prediction ? topPredictions(prediction) : [];
  const level = probability === null ? null : probabilityTone(probability);
  const lost = notice === "연결이 끊겼습니다.";
  return (
    <HomeCard
      id="home-prediction"
      title="AI 이상 예측 요약"
      aside={
        level && (
          <HomeBadge tone={tones[level].tone}>{tones[level].label}</HomeBadge>
        )
      }
      className="home-card--prediction"
    >
      {ml.loading ? (
        <HomeNotice>예측 정보를 불러오는 중입니다.</HomeNotice>
      ) : notice || probability === null ? (
        <HomeNotice tone={lost ? "danger" : "neutral"}>
          {notice || "지금은 예측을 표시할 수 없습니다."}
        </HomeNotice>
      ) : (
        <div className="home-prediction">
          <div className="home-prediction__panel" data-tone={level}>
            <span className="home-prediction__label">에러 확률</span>
            <strong className="home-prediction__value">
              {percent(probability)}
            </strong>
            <div
              className="home-gauge"
              role="img"
              aria-label={`에러 확률 ${percent(probability)}, 경고 기준 ${percent(threshold)}`}
            >
              <span
                className="home-gauge__fill"
                style={{ width: `${Math.min(100, probability * 100)}%` }}
              />
              <span
                className="home-gauge__mark"
                style={{ left: `${Math.min(100, threshold * 100)}%` }}
              />
            </div>
            <div className="home-gauge__scale" aria-hidden="true">
              <span>0%</span>
              <span>기준 {percent(threshold)}</span>
              <span>100%</span>
            </div>
            <p>
              {probability >= 1
                ? "에러가 발견 되었습니다"
                : probability >= threshold
                  ? `경고 기준 ${percent(threshold)}를 초과했습니다.`
                  : `경고 기준 ${percent(threshold)} 미만입니다.`}
            </p>
          </div>
          <div className="home-prediction__panel home-prediction__panel--plain">
            <span className="home-prediction__label">예상 고장 후보 TOP 3</span>
            {rows.length === 0 ? (
              <p className="home-muted">표시할 후보가 없습니다.</p>
            ) : (
              <ul>
                {rows.map((row) => (
                  <li
                    key={row.code}
                    data-tone={probabilityTone(row.probability)}
                  >
                    <strong>{row.code}</strong>
                    <span
                      className="home-bar"
                      role="img"
                      aria-label={`${row.code} ${percent(row.probability)}`}
                    >
                      <span
                        style={{
                          width: `${Math.min(100, row.probability * 100)}%`,
                        }}
                      />
                    </span>
                    <em>{percent(row.probability)}</em>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
      <p className="home-status" data-lost={lost}>
        <span className="home-status__dot" aria-hidden="true" />
        <strong>
          {ml.loading
            ? "예측 상태 확인 중"
            : lost
              ? "예측 수신 중단"
              : notice
                ? "예측 대기 중"
                : "예측 정상 수신 중"}
        </strong>
      </p>
    </HomeCard>
  );
}
