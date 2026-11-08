import { useContext, useEffect, useRef, useState } from "react";
import {
  SettingsContext,
  SettingsUpdateContext,
} from "../components/layout/settings";
import PageTitle from "../components/ui/PageTitle";
import ModelViewer from "../components/dashboard/ModelViewer";
import CctvPanel, { useCctvMode } from "../components/dashboard/CctvPanel";
import DashboardAside from "../components/dashboard/DashboardAside";
import useTelemetryDashboard from "./useTelemetryDashboard";
import useDragScroll from "./useDragScroll";
import {
  sensorCharts,
  sensorValue,
  formatSensor,
  sensorPath,
  sensorStatus,
} from "./telemetryCharts";
import "./DashboardPage.scss";

const charts = sensorCharts;
const noop = () => {};

// Figma 작업프레임(대시보드) 배치와 관련 없는 상단 센서 카드·그래프를 잠시 숨긴다.
// 다시 보이게 하려면 true로 바꾼다.
const SHOW_OTHER_BOXES = false;

export default function DashboardPage({
  onSessionExpired = noop,
  onNavigate,
}: {
  onSessionExpired?: () => void;
  onNavigate?: (page: string) => void;
}) {
  const { pauseModelAnimation } = useContext(SettingsContext);
  const cctvMode = useCctvMode();
  const updateSettings = useContext(SettingsUpdateContext);
  const [refreshInterval, setRefreshInterval] = useState("1");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [hiddenCharts, setHiddenCharts] = useState<string[]>([]);
  const settingsRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  useDragScroll(gridRef);
  const { model, error, now } = useTelemetryDashboard(
    Number(refreshInterval) * 1000,
    onSessionExpired,
  );
  const state = model.snapshot;
  const record = state?.telemetry;
  const status = sensorStatus(model, error, now);
  // 센서 스트림은 현재 BLDC-001 한 대뿐이라, 수신 기록에 설비 ID가 없으면 이 설비로 본다.
  const assetId =
    typeof record?.asset_id === "string" ? record.asset_id : "BLDC-001";

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
        <div className="home-heading">
          <PageTitle>공정 실시간 모니터링 (BAT-TRANSFER-01)</PageTitle>
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
              <div className="sensor-settings-panel__chart sensor-settings-panel__motion">
                <span>3D 움직임 멈추기</span>
                <button
                  type="button"
                  className="sensor-settings-panel__toggle"
                  role="switch"
                  aria-label="3D 움직임 멈추기"
                  aria-checked={pauseModelAnimation}
                  onClick={() =>
                    updateSettings({
                      pauseModelAnimation: !pauseModelAnimation,
                    })
                  }
                >
                  <span />
                </button>
              </div>
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
      <div className="sensor-dashboard__body">
        {SHOW_OTHER_BOXES && (
          <div className="sensor-dashboard__grid" ref={gridRef}>
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
                      <h2>
                        {chart.title}
                        {chart.unit && (
                          <span className="sensor-chart__unit">
                            {" "}
                            [{chart.unit}]
                          </span>
                        )}
                        <span className="sensor-chart__code">
                          {" "}
                          ({chart.code})
                        </span>
                      </h2>
                    </div>
                    <div className="sensor-chart__row">
                      <p className="sensor-chart__value">
                        {formatSensor(value, chart.digits)}
                      </p>
                      <span
                        className="sensor-chart__badge"
                        data-state={
                          value === null
                            ? "none"
                            : status.current
                              ? "live"
                              : "stale"
                        }
                      >
                        {value === null
                          ? "미수신"
                          : status.current
                            ? "수신 중"
                            : "마지막 수신값"}
                      </span>
                    </div>
                    <div className="sensor-chart__plot">
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
                        ) : null}
                      </svg>
                      {!(path && model.samples.length > 1) && (
                        <span className="sensor-chart__placeholder">
                          {value === null ? "미수신" : "표본 수집 중"}
                        </span>
                      )}
                    </div>
                    <p className="sensor-chart__footer">최근 60초</p>
                  </section>
                );
              })}
          </div>
        )}
        <div className="sensor-dashboard__lower sensor-dashboard__lower--stacked">
          <section
            className="sensor-dashboard__placeholder"
            aria-label="3D 모델 뷰어"
          >
            <ModelViewer
              backdrop={cctvMode ? <CctvPanel /> : undefined}
              paused={pauseModelAnimation}
              samples={model.samples}
              errorMessage={error}
            />
          </section>
          <DashboardAside
            onNavigate={onNavigate}
            onSessionExpired={onSessionExpired}
          />
        </div>
      </div>
      {hiddenCharts.length === charts.length && (
        <p className="sensor-dashboard__empty">
          표시할 그래프가 없습니다. 그래프 설정에서 표시할 항목을 선택하세요.
        </p>
      )}
    </div>
  );
}
