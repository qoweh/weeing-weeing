import { analysisProgress } from "./analysisProgress";
import "./analysis-progress.scss";

// 화살표는 다음 단계의 진행 상태를 따라 바뀐다: 진행 중이면 흐르는 애니메이션, 끝나면 고정색.
function arrowState(prev, next) {
  if (next.status === "RUNNING") return "active";
  if (
    next.status === "FAILED" ||
    ["CAUTION", "REVISE", "INSUFFICIENT_EVIDENCE"].includes(next.verdict)
  )
    return "warning";
  if (
    next.status === "COMPLETED" &&
    ["COMPLETED", "SKIPPED"].includes(prev.status)
  )
    return "done";
  return "pending";
}

export default function AnalysisProgress({ result }) {
  const progress = analysisProgress(result);
  if (!progress) return null;
  return (
    <section
      className={`analysis-progress analysis-progress--${progress.tone}`}
      aria-label="AI 분석 진행 상태"
    >
      <div
        className="analysis-progress__headline"
        role="status"
        aria-live="polite"
      >
        {progress.tone === "running" && (
          <span className="analysis-progress__spinner" aria-hidden="true" />
        )}
        <div>
          <strong>{progress.title}</strong>
          <p>{progress.description}</p>
        </div>
      </div>
      <ol className="analysis-progress__steps">
        {progress.steps.flatMap((step, index) => {
          const item = (
            <li
              key={step.role}
              data-status={step.status}
              data-verdict={step.verdict}
            >
              <span className="analysis-progress__marker" aria-hidden="true">
                {step.status === "FAILED" ||
                ["CAUTION", "REVISE", "INSUFFICIENT_EVIDENCE"].includes(
                  step.verdict,
                )
                  ? "!"
                  : step.status === "COMPLETED"
                    ? "✓"
                    : step.status === "SKIPPED"
                      ? "–"
                      : "●"}
              </span>
              <span>
                <strong>{step.label}</strong>
                <small>{step.detail}</small>
              </span>
            </li>
          );
          if (index === progress.steps.length - 1) return [item];
          return [
            item,
            <li
              key={`${step.role}-arrow`}
              className="analysis-progress__arrow"
              data-state={arrowState(step, progress.steps[index + 1])}
              aria-hidden="true"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                  d="M8 2.5v10M3.5 8.5 8 13l4.5-4.5"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </li>,
          ];
        })}
      </ol>
    </section>
  );
}
