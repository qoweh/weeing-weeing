import { useEffect, useRef, useState } from "react";
import PageTitle from "../components/ui/PageTitle";
import useTelemetryDashboard from "./useTelemetryDashboard";
import {
  sensorCharts,
  sensorValue,
  formatSensor,
  sensorPath,
  sensorStatus,
  detectionLabel,
} from "./telemetryCharts";
import "./DashboardPage.scss";

const charts = sensorCharts;
const noop = () => {};

export default function DashboardPage({
  onSessionExpired = noop,
}: {
  onSessionExpired?: () => void;
}) {
  const [refreshInterval, setRefreshInterval] = useState("1");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [hiddenCharts, setHiddenCharts] = useState<string[]>([]);
  const settingsRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const { model, error, now } = useTelemetryDashboard(
    Number(refreshInterval) * 1000,
    onSessionExpired,
  );
  const state = model.snapshot;
  const record = state?.telemetry;
  const status = sensorStatus(model, error, now);
  const measuredAt = record
    ? new Date(record.timestamp).toLocaleTimeString("ko-KR", { hour12: false })
    : "표본 없음";
  const storage =
    state?.db_status === "saved"
      ? "저장 완료"
      : ["failed", "storage_failed"].includes(state?.db_status || "")
        ? "저장 실패"
        : "저장 확인 전";

  useEffect(() => {
    if (!settingsOpen) return;
    function onPointerDown(event: PointerEvent) {
      if (!settingsRef.current?.contains(event.target as Node))
        setSettingsOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSettingsOpen(false);
        settingsButtonRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [settingsOpen]);

  return (
    <div className="sensor-dashboard">
      <div className="sensor-dashboard__header">
        <div>
          <PageTitle>대시보드</PageTitle>
          <p className="sensor-dashboard__description" role="status">
            센서 데이터 추이 · {status.label}
          </p>
        </div>
        <div className="sensor-dashboard__settings" ref={settingsRef}>
          <button
            ref={settingsButtonRef}
            className="sensor-dashboard__settings-button"
            type="button"
            aria-label="그래프 설정"
            aria-expanded={settingsOpen}
            aria-controls="sensor-settings-panel"
            onClick={() => setSettingsOpen((open) => !open)}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path
                d="M10.3 2.8h3.4l.5 2.2c.5.2 1 .4 1.4.6l1.9-1.2 2.4 2.4-1.2 1.9c.2.4.4.9.6 1.4l2.2.5v3.4l-2.2.5c-.2.5-.4 1-.6 1.4l1.2 1.9-2.4 2.4-1.9-1.2c-.4.2-.9.4-1.4.6l-.5 2.2h-3.4l-.5-2.2c-.5-.2-1-.4-1.4-.6l-1.9 1.2-2.4-2.4 1.2-1.9c-.2-.4-.4-.9-.6-1.4l-2.2-.5v-3.4l2.2-.5c.2-.5.4-1 .6-1.4L4.1 6.8l2.4-2.4 1.9 1.2c.4-.2.9-.4 1.4-.6l.5-2.2Z"
                strokeWidth="1.5"
              />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
          {settingsOpen && (
            <section
              id="sensor-settings-panel"
              className="sensor-settings-panel"
              aria-labelledby="sensor-settings-title"
            >
              <div className="sensor-settings-panel__header">
                <h2 id="sensor-settings-title">그래프 설정</h2>
                <button
                  type="button"
                  className="sensor-settings-panel__close"
                  aria-label="설정 닫기"
                  onClick={() => {
                    setSettingsOpen(false);
                    settingsButtonRef.current?.focus();
                  }}
                >
                  ×
                </button>
              </div>
              <h3>갱신 주기</h3>
              <div
                className="sensor-settings-panel__intervals"
                role="group"
                aria-label="갱신 주기"
              >
                {["0.5", "1", "5"].map((interval) => (
                  <button
                    key={interval}
                    type="button"
                    aria-pressed={refreshInterval === interval}
                    onClick={() => setRefreshInterval(interval)}
                  >
                    {interval}초
                  </button>
                ))}
              </div>
              <p>수신 표본은 유지하고 화면 갱신 주기에 적용합니다.</p>
              <div className="sensor-settings-panel__charts">
                <div className="sensor-settings-panel__charts-heading">
                  <h3>그래프 표시</h3>
                  <button
                    type="button"
                    onClick={() =>
                      setHiddenCharts(
                        hiddenCharts.length === charts.length
                          ? []
                          : charts.map((chart) => chart.title),
                      )
                    }
                  >
                    {hiddenCharts.length === charts.length
                      ? "전체 켜기"
                      : "전체 끄기"}
                  </button>
                </div>
                <div className="sensor-settings-panel__chart-grid">
                  {charts.map((chart) => (
                    <div
                      className="sensor-settings-panel__chart"
                      key={chart.title}
                    >
                      <span>{chart.title}</span>
                      <button
                        type="button"
                        className="sensor-settings-panel__toggle"
                        role="switch"
                        aria-label={`${chart.title} 표시`}
                        aria-checked={!hiddenCharts.includes(chart.title)}
                        onClick={() =>
                          setHiddenCharts((current) =>
                            current.includes(chart.title)
                              ? current.filter((title) => title !== chart.title)
                              : [...current, chart.title],
                          )
                        }
                      >
                        <span />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}
        </div>
      </div>
      <div className="sensor-dashboard__connection">
        {state?.context_preset === "UNREAL_STATE" && (
          <strong>
            Unreal 시뮬레이터 상태·트레이 이벤트 연결 · 실제 PLC 확인이
            아닙니다. M04(1초 격자)·M19(승인 기준)는 미평가입니다.
          </strong>
        )}
        {state?.context_preset === "SIM_RPM" && (
          <strong>
            로컬 RPM 시나리오 시험 · 고정 속도를 가정합니다. 실제 PLC 운전
            확인이 아닙니다.
          </strong>
        )}
        <span>측정 시각 {measuredAt}</span>
        <span>{storage}</span>
        <span>
          입구 {detectionLabel(record, "infeed_present")} · 출구{" "}
          {detectionLabel(record, "outfeed_present")}
        </span>
        {state?.run_id && (
          <span className="sensor-dashboard__session">
            감지 세션 {state.run_id}
          </span>
        )}
        {!status.current && record && (
          <strong>
            마지막 수신값입니다. 현재 정상 상태를 뜻하지 않습니다.
          </strong>
        )}
        {model.sessionChanged && (
          <span>
            새 감지 세션에서 그래프를 다시 수집합니다. 이전 사건의 회복을 뜻하지
            않습니다.
          </span>
        )}
        {error && <span role="alert">{error}</span>}
      </div>
      <div className="sensor-dashboard__grid">
        {charts
          .filter((chart) => !hiddenCharts.includes(chart.title))
          .map((chart) => {
            const value = sensorValue(record, chart.field);
            const path = sensorPath(model.samples, chart.field);
            return (
              <section
                className="sensor-chart"
                key={chart.title}
                aria-label={`${chart.title} 센서 그래프`}
                data-sensor-field={chart.field}
                data-current={status.current}
              >
                <div className="sensor-chart__heading">
                  <div>
                    <h2>{chart.title}</h2>
                    <p className="sensor-chart__value">
                      {formatSensor(value, chart.digits)}
                      {chart.unit && (
                        <span className="sensor-chart__unit">
                          {" "}
                          {chart.unit}
                        </span>
                      )}
                    </p>
                  </div>
                  <span>
                    최근 60초 · {status.current ? "수신값" : "마지막 수신값"}
                  </span>
                </div>
                <svg
                  className="sensor-chart__graph"
                  viewBox="0 0 600 80"
                  preserveAspectRatio="none"
                  role="img"
                  aria-label={`${chart.title}의 최근 수신 추이`}
                >
                  <path
                    d="M0 16H600 M0 45H600 M0 74H600"
                    className="sensor-chart__gridline"
                  />
                  {path && model.samples.length > 1 ? (
                    <path d={path} className="sensor-chart__line" />
                  ) : (
                    <text
                      x="300"
                      y="45"
                      textAnchor="middle"
                      className="sensor-chart__placeholder"
                    >
                      {value === null ? "미수신" : "표본 수집 중"}
                    </text>
                  )}
                </svg>
                <div className="sensor-chart__axis">
                  <span>60초 전</span>
                  <span>30초 전</span>
                  <span>0초</span>
                </div>
              </section>
            );
          })}
      </div>
      {hiddenCharts.length === charts.length && (
        <p className="sensor-dashboard__empty">
          표시할 그래프가 없습니다. 그래프 설정에서 표시할 항목을 선택하세요.
        </p>
      )}
    </div>
  );
}
