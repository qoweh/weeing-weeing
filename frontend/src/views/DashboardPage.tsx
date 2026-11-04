import { useEffect, useRef, useState } from "react";
import PageTitle from "../components/ui/PageTitle";
import "./DashboardPage.scss";

const charts = [
  {
    title: "회전 속도",
    value: "1,480",
    unit: "rpm",
    points:
      "0,44 40,34 80,38 120,35 160,48 200,53 240,46 280,44 320,36 360,40 400,47 440,42 480,48 520,45 560,31 600,28",
  },
  {
    title: "DC 입력 전류",
    value: "4.2",
    unit: "A",
    points:
      "0,38 40,41 80,35 120,46 160,53 200,49 240,51 280,48 320,39 360,40 400,46 440,42 480,50 520,46 560,42 600,29",
  },
  {
    title: "DC 버스 전압",
    value: "48.1",
    unit: "V",
    points:
      "0,34 40,43 80,49 120,46 160,51 200,45 240,40 280,36 320,42 360,49 400,40 440,43 480,41 520,27 560,29 600,36",
  },
  {
    title: "모터 외함 온도",
    value: "68.4",
    unit: "℃",
    points:
      "0,38 40,46 80,50 120,40 160,35 200,25 240,26 280,33 320,38 360,39 400,34 440,35 480,32 520,28 560,30 600,42",
  },
  {
    title: "구동측 진동 RMS",
    value: "0.18",
    unit: "g",
    points:
      "0,43 40,46 80,42 120,28 160,25 200,28 240,23 280,32 320,41 360,43 400,35 440,36 480,32 520,39 560,48 600,43",
  },
  {
    title: "구동측 진동 첨도",
    value: "3.1",
    unit: "",
    points:
      "0,49 40,37 80,31 120,29 160,24 200,29 240,39 280,43 320,44 360,43 400,35 440,38 480,34 520,42 560,48 600,42",
  },
  {
    title: "반구동측 진동 RMS",
    value: "0.14",
    unit: "g",
    points:
      "0,39 40,29 80,32 120,28 160,34 200,42 240,45 280,48 320,43 360,38 400,45 440,42 480,47 520,44 560,39 600,35",
  },
  {
    title: "반구동측 진동 첨도",
    value: "2.9",
    unit: "",
    points:
      "0,31 40,32 80,29 120,38 160,46 200,51 240,45 280,44 320,47 360,34 400,37 440,43 480,38 520,34 560,31 600,29",
  },
];

export default function DashboardPage() {
  const [refreshInterval, setRefreshInterval] = useState("1");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [hiddenCharts, setHiddenCharts] = useState<string[]>([]);
  const settingsRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);

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
          <p className="sensor-dashboard__description">
            센서 데이터 추이 · 예시 데이터
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
              <p>실시간 데이터 연결 시 적용 예정</p>
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
      <div className="sensor-dashboard__grid">
        {charts
          .filter((chart) => !hiddenCharts.includes(chart.title))
          .map((chart) => (
            <section
              className="sensor-chart"
              key={chart.title}
              aria-label={`${chart.title} 예시 그래프`}
            >
              <div className="sensor-chart__heading">
                <div>
                  <h2>{chart.title}</h2>
                  <p className="sensor-chart__value">
                    {chart.value}
                    {chart.unit && (
                      <span className="sensor-chart__unit"> {chart.unit}</span>
                    )}
                  </p>
                </div>
                <span>최근 60초 · 예시</span>
              </div>
              <svg
                className="sensor-chart__graph"
                viewBox="0 0 600 80"
                preserveAspectRatio="none"
                role="img"
                aria-label={`${chart.title}의 예시 추이`}
              >
                <path
                  d="M0 16H600 M0 45H600 M0 74H600"
                  className="sensor-chart__gridline"
                />
                <polyline
                  points={chart.points}
                  className="sensor-chart__line"
                />
              </svg>
              <div className="sensor-chart__axis">
                <span>60초 전</span>
                <span>30초 전</span>
                <span>0초</span>
              </div>
            </section>
          ))}
      </div>
      {hiddenCharts.length === charts.length && (
        <p className="sensor-dashboard__empty">
          표시할 그래프가 없습니다. 그래프 설정에서 표시할 항목을 선택하세요.
        </p>
      )}
    </div>
  );
}
