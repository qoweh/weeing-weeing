import "./model-hotspots.scss";

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import {
  formatSensor,
  sensorCharts,
  sensorPath,
  sensorValue,
  type SensorSample,
} from "../../views/telemetryCharts";

// 그래프에 마우스를 올렸을 때 커서 아래에 뜨는 값 박스를 잠시 숨긴다. 다시 보이게 하려면 true로 바꾼다.
const SHOW_HOVER_BOX = false;

type Props = {
  // 있으면 3D 대신 이 내용을 보여 준다(예: CCTV). 이 경우 3D는 그리지 않고, 구역 틀·말풍선·센서 표시는 그대로 쓴다.
  backdrop?: ReactNode;
  onExpand?: () => void;
  samples?: SensorSample[];
  // 오류가 있으면 말풍선 제목 아래에 설명으로 보여준다(없으면 칸을 비운다).
  errorMessage?: string | null;
};

// 상자별 말풍선 정보. 아직 정해지지 않은 상자는 기본 제목과 기본 그래프를 쓴다.
const BUBBLE_INFO: Partial<
  Record<
    Column,
    {
      title: string;
      note: string;
      description: string;
      fields: readonly string[];
    }
  >
> = {
  1: {
    title: "반출부 A02-A03",
    note: "(전원, 전력 상태)",
    description: "DC 입력 전류, DC 버스 전압",
    fields: ["dc_input_current_a", "dc_bus_voltage_v"],
  },
  2: {
    title: "이송부 A01-A02",
    note: "(회전, 구동 상태)",
    description: "회전속도, 구동측 진동 RMS, 구동측 진동 첨도",
    fields: ["rpm", "de_vibration_rms_g", "de_kurtosis"],
  },
  3: {
    title: "반출부 A02-A03",
    note: "(온도, 반구동측 상태)",
    description: "모터 외함 온도, 반구동측 진동 RMS, 반구동측 진동 첨도",
    fields: ["motor_housing_temp_c", "nde_vibration_rms_g", "nde_kurtosis"],
  },
};

// 구역(상자)의 판정: 그 구역 센서 중 가장 나쁜 단계(경고 > 주의 > 정상).
function zoneLevel(column: Column, record: unknown): SensorLevel {
  const fields = BUBBLE_INFO[column]?.fields ?? [];
  const levels = fields.map((field) =>
    sensorLevel(field, sensorValue(record as never, field)),
  );
  return levels.includes("warning")
    ? "warning"
    : levels.includes("caution")
      ? "caution"
      : "normal";
}

// 센서별 판정 범위. 백엔드 detector(BTT-RULE v2.0, builtin_rules.py NUMERIC_RULES)와 같은 값이다.
// low~high 안이면 정상, 벗어나면 주의, errorLow 이하·errorHigh 이상이면 경고. 백엔드 값을 바꾸면 여기도 고친다.
// 백엔드는 RUN·기동 3초 같은 운전 조건과 지속 시간도 보지만, 여기서는 최신 값만 본다.
const SENSOR_RANGES: Record<
  string,
  { low: number; high: number; errorLow: number; errorHigh: number }
> = {
  rpm: { low: 1000, high: 1030, errorLow: 990, errorHigh: 1040 },
  dc_input_current_a: {
    low: 0.089963,
    high: 0.093786,
    errorLow: 0.080967,
    errorHigh: 0.103165,
  },
  dc_bus_voltage_v: { low: 20, high: 25, errorLow: 18, errorHigh: 27 },
  motor_housing_temp_c: { low: 45, high: 85, errorLow: 40, errorHigh: 90 },
  de_vibration_rms_g: {
    low: 0.040396,
    high: 0.080601,
    errorLow: 0.036356,
    errorHigh: 0.088661,
  },
  de_kurtosis: {
    low: 3.5511,
    high: 7.0661,
    errorLow: 2.8836,
    errorHigh: 7.7727,
  },
  nde_vibration_rms_g: {
    low: 0.049179,
    high: 0.062322,
    errorLow: 0.044261,
    errorHigh: 0.068554,
  },
  nde_kurtosis: {
    low: 3.3565,
    high: 5.477,
    errorLow: 2.7413,
    errorHigh: 6.0248,
  },
};

type SensorLevel = "normal" | "caution" | "warning";

// 값이 없으면(미수신) 범위를 벗어난 것이 아니므로 정상 색을 유지한다.
function sensorLevel(field: string, value: number | null): SensorLevel {
  const range = SENSOR_RANGES[field];
  if (value === null || !range) return "normal";
  if (value <= range.errorLow || value >= range.errorHigh) return "warning";
  if (value < range.low || value > range.high) return "caution";
  return "normal";
}

const LEVEL_LABEL = { normal: "", caution: " (주의)", warning: " (경고)" };

// 1번 상자를 누르면 2·3번 상자 영역에 말풍선 하나로 띄우는 센서 그래프 박스 3개.
const BUBBLE_FIELDS = [
  "rpm",
  "motor_housing_temp_c",
  "de_vibration_rms_g",
] as const;

function GraphBox({
  field,
  samples,
}: {
  field: string;
  samples: SensorSample[];
}) {
  // 그래프 위에 마우스를 올리면 커서 아래 말풍선 박스에 그 시점의 값을 보여준다.
  // x: 0~600 그래프 좌표, px·py·width: 그래프 영역 안의 커서 위치(px).
  const [pointer, setPointer] = useState<{
    x: number;
    px: number;
    py: number;
    width: number;
  } | null>(null);
  const hoverX = pointer?.x ?? null;
  const chart = sensorCharts.find((item) => item.field === field);
  if (!chart) return null;
  const latest = sensorValue(samples.at(-1)?.record, field);
  const path = sensorPath(samples, field);
  const ready = path !== "" && samples.length > 1;
  const level = sensorLevel(field, latest);

  let hover: { value: number; secondsAgo: number } | null = null;
  if (hoverX !== null && ready) {
    const end = samples.at(-1)!.time;
    const time = end - 60_000 + hoverX * 100;
    let best: SensorSample | null = null;
    for (const sample of samples) {
      if (sensorValue(sample.record, field) === null) continue;
      if (!best || Math.abs(sample.time - time) < Math.abs(best.time - time))
        best = sample;
    }
    const value = best ? sensorValue(best.record, field) : null;
    if (best && value !== null)
      hover = { value, secondsAgo: Math.round((end - best.time) / 1000) };
  }

  return (
    <section
      className={`model-viewer__graph-box${level === "normal" ? "" : ` model-viewer__graph-box--${level}`}`}
      aria-label={`${chart.title} 센서 그래프${LEVEL_LABEL[level]}`}
    >
      <p className="model-viewer__bubble-title">
        {chart.title}
        {chart.unit && ` [${chart.unit}]`}
        <b>{formatSensor(latest, chart.digits)}</b>
      </p>
      <div
        className="model-viewer__bubble-plot"
        onPointerMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          if (rect.width > 0)
            setPointer({
              x: Math.min(
                600,
                Math.max(0, ((event.clientX - rect.left) / rect.width) * 600),
              ),
              px: event.clientX - rect.left,
              py: event.clientY - rect.top,
              width: rect.width,
            });
        }}
        onPointerLeave={() => setPointer(null)}
      >
        <svg
          viewBox="0 0 600 80"
          preserveAspectRatio="none"
          role="img"
          aria-label={`${chart.title}의 최근 수신 추이`}
        >
          {ready ? (
            <path d="M0 16H600 M0 45H600 M0 74H600" className="grid" />
          ) : (
            // 미수신·수집 중에는 얇은 실선으로 그리고, 글자가 놓이는 가운데 구간의 선은 비운다.
            <path
              d={`M0 16H600 M0 74H600 M0 45H${latest === null ? 230 : 190} M${latest === null ? 370 : 410} 45H600`}
              className="grid grid--empty"
            />
          )}
          {ready && <path d={path} className="line" />}
          {hover && hoverX !== null && (
            <path d={`M${hoverX} 0V80`} className="cursor" />
          )}
        </svg>
        {SHOW_HOVER_BOX && hover && pointer && (
          <span
            className={`model-viewer__bubble-hover model-viewer__bubble-hover--${sensorLevel(field, hover.value)}`}
            style={{
              // 기본은 커서 아래, 그래프 아래쪽에 있으면 위로 뒤집고, 좌우는 영역 안으로 맞춘다.
              left: Math.min(Math.max(pointer.px, 52), pointer.width - 52),
              top: pointer.py < 40 ? pointer.py + 18 : pointer.py - 14,
              transform:
                pointer.py < 40 ? "translateX(-50%)" : "translate(-50%, -100%)",
            }}
          >
            <b>
              {formatSensor(hover.value, chart.digits)}
              {chart.unit && ` ${chart.unit}`}
            </b>
            <small>
              {hover.secondsAgo === 0 ? "현재" : `${hover.secondsAgo}초 전`}
            </small>
          </span>
        )}
        {!ready && (
          <span className="model-viewer__bubble-empty">
            {latest === null ? "미수신" : "표본 수집 중"}
          </span>
        )}
      </div>
    </section>
  );
}

// 말풍선 왼쪽: 같은 줄 센서 그래프의 상태. 주의·경고이면 어떤 기준을 벗어났는지 보여준다.
function ErrorCell({
  field,
  record,
}: {
  field: string;
  record: SensorSample["record"] | undefined;
}) {
  const value = sensorValue(record, field);
  const level = sensorLevel(field, value);
  const chart = sensorCharts.find((item) => item.field === field);
  const range = SENSOR_RANGES[field];
  if (!chart || !range) return null;
  const unit = chart.unit && ` ${chart.unit}`;
  if (value === null)
    return (
      <div className="model-viewer__error model-viewer__error--empty">
        <b>{chart.title}</b>
        <p>미수신</p>
      </div>
    );
  if (level === "normal")
    return (
      <div className="model-viewer__error model-viewer__error--normal">
        <b>
          {chart.title}
          <em>정상</em>
        </b>
        <p>정상 범위 안입니다.</p>
      </div>
    );
  const high = value > range.high;
  const bound =
    level === "warning"
      ? high
        ? range.errorHigh
        : range.errorLow
      : high
        ? range.high
        : range.low;
  return (
    <div className={`model-viewer__error model-viewer__error--${level}`}>
      <b>
        {chart.title}
        <em>{level === "warning" ? "경고" : "주의"}</em>
      </b>
      <dl>
        <dt>현재</dt>
        <dd>
          {formatSensor(value, chart.digits)}
          {unit}
        </dd>
        <dt>{high ? "상한" : "하한"} 기준</dt>
        <dd>
          {formatSensor(bound, chart.digits)}
          {unit}{" "}
          {level === "warning"
            ? high
              ? "이상"
              : "이하"
            : high
              ? "초과"
              : "미만"}
        </dd>
        <dt>정상 범위</dt>
        <dd>
          {formatSensor(range.low, chart.digits)} ~{" "}
          {formatSensor(range.high, chart.digits)}
        </dd>
      </dl>
    </div>
  );
}

type Column = 1 | 2 | 3;

// 눌린 상자를 뺀 나머지 상자 영역에 말풍선을 채운다.
// 1번·3번이면 붙어 있는 두 상자에 하나, 2번이면 3번 상자 영역에 하나.
function bubblesFor(active: Column) {
  const fields = BUBBLE_INFO[active]?.fields ?? BUBBLE_FIELDS;
  if (active === 1)
    return [{ from: 2, to: 3, tail: "left", fields, row: false, inset: 110 }];
  if (active === 3)
    return [{ from: 1, to: 2, tail: "right", fields, row: false, inset: 110 }];
  // 가운데 상자는 오른쪽 상자 영역에 말풍선 하나를 띄운다.
  // 3번 영역 바깥쪽에 붙지 않게 왼쪽(2번 영역 쪽)으로 inset(px)만큼 들여 넓힌다. 꼬리는 여전히 왼쪽의 2번 상자를 가리킨다.
  return [{ from: 3, to: 3, tail: "left", fields, row: false, inset: 240 }];
}

function GraphBubble({
  from,
  to,
  tail,
  fields,
  row,
  inset = 0,
  samples,
  title,
  note,
  description,
  errorMessage,
  onClose,
}: {
  from: Column;
  to: Column;
  tail: string;
  fields: readonly string[];
  row: boolean;
  inset?: number;
  samples: SensorSample[];
  title: string;
  note?: string;
  description?: string;
  errorMessage?: string | null;
  onClose: () => void;
}) {
  const bubbleRef = useRef<HTMLDivElement>(null);

  // 내용만큼 높이가 늘어나되 창 아래로 넘지 않게 하고, 넘치면 내부 스크롤로 넘긴다.
  useLayoutEffect(() => {
    const fit = () => {
      const el = bubbleRef.current;
      if (!el) return;
      const zoom =
        parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue(
            "--screen-zoom",
          ),
        ) || 1;
      const top = el.getBoundingClientRect().top;
      el.style.maxHeight = `${Math.max(120, (window.innerHeight - top - 16) / zoom)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [samples.length, fields.length]);

  return (
    <div
      ref={bubbleRef}
      className={`model-viewer__bubble model-viewer__bubble--tail-${tail}`}
      style={{
        // 눌린 상자 쪽에서 가까운 변에 붙이고, 너비는 영역 폭을 넘지 않는 선에서 좁게 둔다.
        ...(tail === "left"
          ? { left: `calc(${(from - 1) / 3} * 100% + 22px - ${inset}px)` }
          : { right: `calc(${(3 - to) / 3} * 100% + 22px - ${inset}px)` }),
        width: `min(560px, calc(${(to - from + 1) / 3} * 100% - 44px + ${inset}px))`,
      }}
      role="region"
      aria-label="센서 그래프"
      onClick={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        className="model-viewer__bubble-close"
        aria-label="말풍선 닫기"
        onClick={onClose}
      >
        ×
      </button>
      <div className="model-viewer__bubble-scroll">
        <header className="model-viewer__bubble-head">
          <strong>
            {title}
            {note && <small>{note}</small>}
          </strong>
          {description && <span>{description}</span>}
          {errorMessage && (
            <span className="model-viewer__bubble-error" role="alert">
              {errorMessage}
            </span>
          )}
        </header>
        <div className="model-viewer__bubble-body">
          {fields.map((field) => (
            <div key={field} className="model-viewer__bubble-row">
              <ErrorCell field={field} record={samples.at(-1)?.record} />
              <GraphBox field={field} samples={samples} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function ModelViewer({
  backdrop,
  onExpand,
  samples = [],
  errorMessage,
}: Props) {
  const [bubbleColumn, setBubbleColumn] = useState<Column | null>(null);
  const downRef = useRef<{ x: number; y: number } | null>(null);

  return (
    <div className="model-viewer">
      <div
        className="model-viewer__stage"
        onPointerDown={(event) => {
          downRef.current = { x: event.clientX, y: event.clientY };
        }}
        onClick={(event) => {
          const down = downRef.current;
          if (!down || (event.target as HTMLElement).closest("button")) return;
          // 3D를 돌리려고 끈 경우(5px 넘게 움직임)는 클릭으로 보지 않는다.
          if (Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5)
            return;
          const rect = event.currentTarget.getBoundingClientRect();
          const x = (event.clientX - rect.left) / rect.width;
          const column: Column = x < 1 / 3 ? 1 : x < 2 / 3 ? 2 : 3;
          setBubbleColumn((current) => (current === column ? null : column));
        }}
      >
        <div className="model-viewer__canvas">{backdrop}</div>
        <div className="model-viewer__frames" aria-hidden="true">
          {([1, 2, 3] as const).map((column) => {
            const level = zoneLevel(column, samples.at(-1)?.record);
            return (
              <div
                key={`${column}-${level}`}
                className={`model-viewer__frame${level === "normal" ? "" : ` model-viewer__frame--${level}`}`}
              />
            );
          })}
        </div>
        {bubbleColumn &&
          bubblesFor(bubbleColumn).map((bubble) => (
            <GraphBubble
              key={`${bubbleColumn}-${bubble.from}`}
              from={bubble.from as Column}
              to={bubble.to as Column}
              tail={bubble.tail}
              fields={bubble.fields}
              row={bubble.row}
              inset={"inset" in bubble ? bubble.inset : 0}
              samples={samples}
              title={BUBBLE_INFO[bubbleColumn]?.title ?? "센서 실시간 추이"}
              note={BUBBLE_INFO[bubbleColumn]?.note}
              description={BUBBLE_INFO[bubbleColumn]?.description}
              errorMessage={errorMessage}
              onClose={() => setBubbleColumn(null)}
            />
          ))}
        {onExpand && (
          <button
            type="button"
            className="model-viewer__expand"
            aria-label="3D 뷰어 크게 보기"
            title="크게 보기"
            onClick={onExpand}
          >
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path
                d="M10 2h4v4M6 14H2v-4M14 2l-5 5M2 14l5-5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
