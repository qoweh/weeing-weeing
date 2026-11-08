import "./model-hotspots.scss";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { applySurface, type SurfaceKind } from "./surfaceMaterials";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import {
  formatSensor,
  sensorCharts,
  sensorPath,
  sensorValue,
  type SensorSample,
} from "../../views/telemetryCharts";

// 그래프에 마우스를 올렸을 때 커서 아래에 뜨는 값 박스를 잠시 숨긴다. 다시 보이게 하려면 true로 바꾼다.
const SHOW_HOVER_BOX = false;

// 컨베이어 벨트 회전. GLB에는 Blender의 텍스처 스크롤 애니메이션이 담기지 않으므로 코드에서 텍스처를 흘린다.
// BELT_DIRECTION: 1이면 벨트 윗면이 기계에서 멀어지는 쪽으로, -1이면 기계 쪽으로 움직인다(모델 기준, 좌우 반전과 무관).
const MODEL_SCALE = 1.5;
// 화면 가로 가운데에 맞출 점: 바닥(GLB의 Floor 3장, X -1.23~10.12)의 앞쪽 가장자리 중심. MODEL_SCALE·MODEL_MIRROR를 곱한 월드 좌표다.
const FLOOR_FRONT_CENTER = [4.4424, 0, 2.5358] as const;
// 모델 좌우 반전. -1이면 X를 뒤집어 기계가 오른쪽, 컨베이어가 왼쪽에 놓인다(1이면 원래대로). 카메라·상자 위치도 이 값을 따른다.
const MODEL_MIRROR = -1;
// 천장 램프 위치(Blender 좌표, 좌우 반전 전)와 점광원 세기
// 원본 텍스처가 없어 절차적 표면(골판지 골, 도장, 알갱이)을 입힐 재질
const SURFACE_BY_MATERIAL: Record<string, SurfaceKind | undefined> = {
  Box_Cardboard: "hull",
  FW_FB_Cabinet: "hull",
  FW_FB_SteelBlue: "hull",
  FW_FB_SteelGray: "hull",
  FW_FB_Cladding: "hull",
  FW_FB_RollerDoor: "hull",
  FW_FB_DrumRed: "hull",
  FW_FQ_Duct: "hull",
  FW_FB_BlackPlastic: "plastic",
};
// 벨트 위 상자는 GLB에 갈색 골판지로 들어 있어, 테란 보급 상자(붉은 금속 + 주황 띠) 색으로 코드에서 바꾼다.
const RECOLOR_BY_MATERIAL: Record<string, string | undefined> = {
  Box_Cardboard: "#612e27",
  Box_Tape: "#c98f1a",
};
// 텍스처는 두고 색만 곱해 어둡게 하는 재질(바닥). Blender의 Floor 재질과 같은 값이다.
const TINT_BY_MATERIAL: Record<string, string | undefined> = {
  Floor: "#4d535b",
};
// 신호등 발광 세기. 너무 크면 ACES 톤매핑에서 색이 하얗게 날아간다.
const SIGNAL_INTENSITY = 2.8;
// 레일 신호등(FactoryBackground.glb의 FW_Signal_Lamp_N). 번호 -> 말풍선 칸(화면 왼쪽부터 1~3)과 같은 구간.
// 첫 번째 섹션(화면 왼쪽 끝) 바닥에 놓인 2단 상자 더미를 치운다.
// 배경 GLB의 골판지·테이프 메쉬는 상자 전부가 한 메쉬라, 더미가 있는 구간(원본 X 860 이상)의 삼각형만 뺀다.
const PILE_MIN_X = 860;
function removeFirstSectionPile(root: THREE.Object3D) {
  root.traverse((child) => {
    if (
      !(child instanceof THREE.Mesh) ||
      !/^FW_Box_(Cardboard|Tape)$/.test(child.name)
    )
      return;
    const geometry = child.geometry as THREE.BufferGeometry;
    const index = geometry.index;
    if (!index) return;
    const position = geometry.attributes.position;
    const kept: number[] = [];
    for (let i = 0; i < index.count; i += 3) {
      const x =
        (position.getX(index.getX(i)) +
          position.getX(index.getX(i + 1)) +
          position.getX(index.getX(i + 2))) /
        3;
      if (x < PILE_MIN_X)
        kept.push(index.getX(i), index.getX(i + 1), index.getX(i + 2));
    }
    geometry.setIndex(kept);
  });
}

// 신호등 후광 크기(램프 크기의 배수)와 불투명도.
const HALO_SCALE = 5;
const HALO_OPACITY = 0.85;
const SIGNAL_COLUMN: Record<number, Column> = { 1: 3, 2: 2, 3: 1 };
const SIGNAL_COLOR = {
  normal: "#18ff48",
  caution: "#ffa000",
  warning: "#ff1414",
} as const;
// 카메라 세로 화각(도). 작을수록 원근감이 약하다. 같은 화면 크기를 유지하도록 카메라 거리는 화각에 맞춰 늘린다.
const CAMERA_FOV = 26;
// CAMERA_FOV를 기준으로 맞춘 화면 가로/세로 비율(3D 영역 2000x490). 이 비율에서 화각이 CAMERA_FOV다.
const REFERENCE_ASPECT = 2000 / 490;
// 세로로 긴 화면에서 카메라를 뒤로 물리는 최대 배율.
const CAMERA_MAX_DOLLY = 1.3;
// 카메라를 물렸을 때 화면을 위로 미는 비율(화면 높이 기준).
const VIEW_RISE = 0.3;
// 세로로 긴 화면에서 카메라가 추가로 다가가는 배율(1보다 작을수록 확대).
const MOBILE_ZOOM = 0.85;
// 1보다 작으면 그만큼 가까이 다가가 바닥·벽 가장자리 밖의 빈 배경이 안 보이게 한다.
const CAMERA_DISTANCE_TRIM = 0.78;
const LAMP_COLUMNS = [-10, 217, 444, 671, 898];
const LAMP_ROWS = [-150, 0, 150];
const LAMP_INTENSITY = 12;
// 벨트 위 상자(GLB의 Box_01, Box_02 ...). 벨트 윗면과 같은 속도·방향(BELT_DIRECTION)으로 흘러간다.
// BELT_TRAVEL_PER_LOOP: 텍스처가 한 바퀴 돌 때 벨트 윗면이 움직이는 거리, BOX_X_RANGE: 상자가 지나가는 X 구간(둘 다 MODEL_SCALE 곱하기 전 값).
const BOX_NAME = /^Box_\d+$/;
const BELT_TRAVEL_PER_LOOP = 8.02;
const BOX_X_RANGE = [0.8, 9.86] as const;
const BELT_MATERIAL = "Belt_Exterior";
// 벨트 텍스처가 한 바퀴 도는 시간(초). 상자 속도도 이 값을 따라 벨트 윗면과 항상 같다.
// 줄무늬 간격이 0.057이라 너무 빠르면 프레임이 낮을 때(약 40fps 이하) 줄무늬가 멈추거나 거꾸로 가는 것처럼 보여
// 상자만 빨라 보인다. 20초면 24fps 이상에서 정상 방향으로 보인다(속도 약 0.6/초). 값을 키우면 더 느려진다.
const BELT_LOOP_SECONDS = 20;
// 지금은 1: 기계(화면 오른쪽)에서 상자가 나와 왼쪽으로 흘러간다.
const BELT_DIRECTION = 1;

// 모델 위의 녹색 선택 버튼(표시 지점)을 숨긴다. 다시 보이게 하려면 true로 바꾼다.
const SHOW_HOTSPOTS = false;

const HOTSPOTS = [
  { id: "front", label: "정면 표시 지점", point: [-0.094, 0.12] },
  { id: "right", label: "우측면 표시 지점", point: [0.022, -0.067] },
] as const;
const hotspots: readonly (typeof HOTSPOTS)[number][] = SHOW_HOTSPOTS
  ? HOTSPOTS
  : [];

type Props = {
  // 있으면 3D 대신 이 내용을 보여 준다(예: CCTV). 이 경우 3D는 그리지 않고, 구역 틀·말풍선·센서 표시는 그대로 쓴다.
  backdrop?: ReactNode;
  paused?: boolean;
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
          {unit} {level === "warning" ? (high ? "이상" : "이하") : high ? "초과" : "미만"}
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
  paused = false,
  onExpand,
  samples = [],
  errorMessage,
}: Props) {
  const [bubbleColumn, setBubbleColumn] = useState<Column | null>(null);
  const downRef = useRef<{ x: number; y: number } | null>(null);
  const markerRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [openDetail, setOpenDetail] = useState<string | null>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(paused);
  const samplesRef = useRef(samples);
  samplesRef.current = samples;
  const [status, setStatus] = useState("모델을 불러오는 중입니다.");
  const hasBackdrop = backdrop != null;
  pausedRef.current = paused;

  useEffect(() => {
    if (hasBackdrop || paused) return;
    const host = hostRef.current;
    if (!host) return;
    setStatus("모델을 불러오는 중입니다.");
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setStatus("3D 뷰어를 불러오지 못했습니다.");
      return;
    }
    let disposed = false;
    let model: THREE.Group | undefined;
    let background: THREE.Group | undefined;
    let mixer: THREE.AnimationMixer | undefined;
    let beltPhase = 0;
    let boxPhase = 0;
    const boxes: {
      object: THREE.Object3D;
      y: number;
      z: number;
      offset: number;
    }[] = [];
    const signals: {
      material: THREE.MeshStandardMaterial;
      column: Column;
      halo: THREE.Sprite;
    }[] = [];
    // 신호등 둘레 후광: 중심이 밝고 가장자리로 번지는 원형 그라데이션(흰색, 색은 스프라이트 색으로 입힌다).
    const haloCanvas = document.createElement("canvas");
    haloCanvas.width = haloCanvas.height = 64;
    const haloContext = haloCanvas.getContext("2d");
    if (haloContext) {
      const gradient = haloContext.createRadialGradient(32, 32, 0, 32, 32, 32);
      gradient.addColorStop(0, "rgba(255,255,255,1)");
      gradient.addColorStop(0.25, "rgba(255,255,255,0.5)");
      gradient.addColorStop(1, "rgba(255,255,255,0)");
      haloContext.fillStyle = gradient;
      haloContext.fillRect(0, 0, 64, 64);
    }
    const haloTexture = new THREE.CanvasTexture(haloCanvas);
    let signalKey: unknown = null;
    const beltTextures: { texture: THREE.Texture; base: number }[] = [];
    const anchors: { anchor: THREE.Object3D; id: string }[] = [];
    const raycaster = new THREE.Raycaster();
    const world = new THREE.Vector3();
    const screen = new THREE.Vector3();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    // 하늘 HDRI 환경광은 너무 밝아 쓰지 않는다. 밝기는 아래 조명 세기로 조절한다.
    scene.background = new THREE.Color(0xdde3ea);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8d939c, 0.7));
    const sun = new THREE.DirectionalLight(0xffffff, 0.8);
    sun.position.set(-3, 8, 6);
    scene.add(sun);
    // 공장 천장 조명: Blender 램프 위치(5열 x 3줄)에 은은한 점광원을 둔다. 밝기는 intensity로 조절한다.
    const unit = MODEL_SCALE * 0.01;
    LAMP_COLUMNS.forEach((lampX) =>
      LAMP_ROWS.forEach((lampY) => {
        const lamp = new THREE.PointLight(0xfff0d8, LAMP_INTENSITY, 16, 2);
        lamp.position.set(
          MODEL_MIRROR * unit * lampX,
          unit * 400,
          -unit * lampY,
        );
        scene.add(lamp);
      }),
    );
    const camera = new THREE.PerspectiveCamera(CAMERA_FOV, 1, 1, 100);
    // 모델을 정면에서 30도로 내려다본다. 기준 화각 40도에서 목표점까지 거리 10(높이 5, 앞 8.66)이었고,
    // 화각을 줄인 만큼 같은 비율로 멀리 가서 화면에 보이는 범위는 그대로 둔다.
    const distanceScale =
      (CAMERA_DISTANCE_TRIM * Math.tan(THREE.MathUtils.degToRad(20))) /
      Math.tan(THREE.MathUtils.degToRad(CAMERA_FOV / 2));
    camera.position.set(
      MODEL_MIRROR * 4.05,
      1 + 5 * distanceScale,
      8.66 * distanceScale,
    );
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    // 카메라 고정: 마우스로 회전·확대·이동하지 못하게 한다. 다시 움직이게 하려면 true로 바꾼다.
    controls.enableRotate = false;
    controls.enableZoom = false;
    controls.enablePan = false;
    // 터치패드 두 손가락 가로 스와이프가 브라우저 뒤로가기로 이어지지 않게, 3D 영역 위에서만 막는다.
    // 말풍선·테두리 같은 덮개 위에서도 막도록 캔버스가 아닌 3D 영역 전체(.model-viewer)에 건다.
    // 세로 스크롤은 그대로 페이지에 전달한다.
    const swipeArea = host.closest<HTMLElement>(".model-viewer") ?? host;
    const rootStyle = document.documentElement.style;
    const blockSwipeBack = (event: WheelEvent) => {
      if (
        event.deltaX !== 0 &&
        Math.abs(event.deltaX) >= Math.abs(event.deltaY) * 0.3
      ) {
        event.preventDefault();
      }
    };
    const lockSwipeBack = () => {
      rootStyle.overscrollBehaviorX = "none";
    };
    const unlockSwipeBack = () => {
      rootStyle.overscrollBehaviorX = "";
    };
    swipeArea.addEventListener("wheel", blockSwipeBack, { passive: false });
    swipeArea.addEventListener("pointerenter", lockSwipeBack);
    swipeArea.addEventListener("pointerleave", unlockSwipeBack);
    controls.target.set(MODEL_MIRROR * 4.05, 1, 0);
    controls.update();
    // 처음 카메라 자세. 화면을 얼마나 밀지 계산할 때만 쓴다(사용자가 돌려 본 뒤에도 같은 값을 쓴다).
    const baseCamera = camera.clone();
    const basePosition = camera.position.clone();
    const focus = controls.target.clone();
    const floorCenter = new THREE.Vector3(
      MODEL_MIRROR * FLOOR_FRONT_CENTER[0] * MODEL_SCALE,
      FLOOR_FRONT_CENTER[1],
      FLOOR_FRONT_CENTER[2] * MODEL_SCALE,
    );
    const resize = () => {
      if (!host.clientWidth || !host.clientHeight) return;
      camera.aspect = host.clientWidth / host.clientHeight;
      // 화면 비율이 달라져도 기준 화면(REFERENCE_ASPECT)과 가로로 보이는 범위가 같도록 세로 화각을 맞춘다.
      // 기준보다 가로로 길면 화각을 줄여 위아래를 자른다. 세로로 길면(모바일) 화각은 두고 카메라를 뒤로 물려 같은 가로 범위를 보인다.
      // 화각을 벌리면 원근감이 커지고, 너무 물러나면 모델 밖 빈 배경이 보이므로 물러나는 거리에 상한을 둔다.
      const wanted = Math.min(
        CAMERA_MAX_DOLLY,
        Math.max(1, REFERENCE_ASPECT / camera.aspect),
      );
      // 세로로 긴 화면은 가장자리의 빈 배경이 보이지 않도록 MOBILE_ZOOM만큼 더 다가간다.
      const dolly = wanted > 1 ? wanted * MOBILE_ZOOM : 1;
      camera.position
        .copy(basePosition)
        .sub(focus)
        .multiplyScalar(dolly)
        .add(focus);
      baseCamera.position.copy(camera.position);
      camera.fov = Math.min(
        CAMERA_FOV,
        THREE.MathUtils.radToDeg(
          2 *
            Math.atan(
              (Math.tan(THREE.MathUtils.degToRad(CAMERA_FOV / 2)) *
                REFERENCE_ASPECT) /
                camera.aspect,
            ),
        ),
      );
      baseCamera.fov = camera.fov;
      // 카메라 각도는 그대로 두고, 바닥 앞쪽 가장자리의 중심이 화면 가로 가운데에 오도록 화면 전체를 민다.
      baseCamera.aspect = camera.aspect;
      baseCamera.filmOffset = 0;
      baseCamera.updateProjectionMatrix();
      baseCamera.updateMatrixWorld();
      const shift = -floorCenter.clone().project(baseCamera).x / 2;
      const filmWidth = camera.filmGauge * Math.min(camera.aspect, 1);
      camera.filmOffset =
        -shift *
        filmWidth *
        2 *
        Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) *
        camera.aspect;
      // 카메라를 물린 만큼 화면을 위로 밀어, 바닥 아래쪽 모델 밖 빈 배경이 덜 보이게 한다.
      const rise = Math.min(1, Math.max(0, dolly - 1)) * VIEW_RISE;
      camera.setViewOffset(
        host.clientWidth,
        host.clientHeight,
        0,
        -rise * host.clientHeight,
        host.clientWidth,
        host.clientHeight,
      );
      camera.updateProjectionMatrix();
      renderer.setSize(host.clientWidth, host.clientHeight);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();
    const draco = new DRACOLoader();
    draco.setDecoderPath("/draco/");
    // 환경광이 없으면 금속 재질이 까맣게 보이므로 금속성을 낮춘다.
    // 바닥 벽돌 재질에는 노말맵이 없어 평평해 보인다. 색 텍스처의 밝기로 요철(노말맵)을 만들어 입힌다.
    const addNormalFromAlbedo = (material: THREE.MeshStandardMaterial) => {
      const map = material.map;
      const source = map?.image as CanvasImageSource | undefined;
      if (!map || !source || material.normalMap) return;
      const size = 512;
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = size;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) return;
      context.drawImage(source, 0, 0, size, size);
      const pixels = context.getImageData(0, 0, size, size);
      const height = new Float32Array(size * size);
      for (let i = 0; i < height.length; i++) {
        const p = i * 4;
        height[i] =
          (pixels.data[p] * 0.3 +
            pixels.data[p + 1] * 0.59 +
            pixels.data[p + 2] * 0.11) /
          255;
      }
      const at = (x: number, y: number) =>
        height[((y + size) % size) * size + ((x + size) % size)];
      const strength = 4;
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          const dx = (at(x + 1, y) - at(x - 1, y)) * strength;
          const dy = (at(x, y + 1) - at(x, y - 1)) * strength;
          const length = Math.hypot(dx, dy, 1);
          const p = (y * size + x) * 4;
          pixels.data[p] = ((-dx / length) * 0.5 + 0.5) * 255;
          pixels.data[p + 1] = ((dy / length) * 0.5 + 0.5) * 255;
          pixels.data[p + 2] = ((1 / length) * 0.5 + 0.5) * 255;
          pixels.data[p + 3] = 255;
        }
      }
      context.putImageData(pixels, 0, 0);
      // clone()은 이미지를 공유해 색 맵까지 바뀌므로 새 텍스처를 만들고 배치 값만 복사한다.
      const normalMap = new THREE.CanvasTexture(canvas);
      normalMap.colorSpace = THREE.NoColorSpace;
      normalMap.flipY = map.flipY;
      normalMap.wrapS = map.wrapS;
      normalMap.wrapT = map.wrapT;
      normalMap.repeat.copy(map.repeat);
      normalMap.offset.copy(map.offset);
      normalMap.center.copy(map.center);
      normalMap.rotation = map.rotation;
      normalMap.channel = map.channel;
      material.normalMap = normalMap;
      material.normalScale.set(1, 1);
      material.needsUpdate = true;
    };
    const softenMetal = (object: THREE.Object3D) => {
      object.traverse((child) => {
        if (!(child instanceof THREE.Mesh)) return;
        const materials = Array.isArray(child.material)
          ? child.material
          : [child.material];
        materials.forEach((material) => {
          if (!(material instanceof THREE.MeshStandardMaterial)) return;
          material.metalness = Math.min(material.metalness, 0.3);
          const tint = TINT_BY_MATERIAL[material.name];
          if (tint) material.color.set(tint);
          const recolor = RECOLOR_BY_MATERIAL[material.name];
          if (recolor) {
            material.map = null;
            material.color.set(recolor);
            material.roughness = 0.5;
          }
          if (material.name === "Floor") addNormalFromAlbedo(material);
          const surface = SURFACE_BY_MATERIAL[material.name];
          if (surface) applySurface(material, surface);
        });
      });
    };
    const disposeModel = (object: THREE.Object3D) => {
      object.traverse((child) => {
        if (!(child instanceof THREE.Mesh)) return;
        child.geometry.dispose();
        const materials = Array.isArray(child.material)
          ? child.material
          : [child.material];
        materials.forEach((material) => {
          Object.values(material).forEach((value) => {
            if (value instanceof THREE.Texture) value.dispose();
          });
          material.dispose();
        });
      });
    };
    // 공장 배경(벽·기둥·지붕 트러스·설비). Blender의 웹용 배경을 재질별로 합쳐 내보냈고, 모델과 같은 배율·좌우 반전을 적용한다.
    new GLTFLoader()
      .setDRACOLoader(draco)
      .load("/models/FactoryBackground.glb", (gltf) => {
        if (disposed) {
          disposeModel(gltf.scene);
          return;
        }
        background = gltf.scene;
        background.scale.set(
          MODEL_MIRROR * MODEL_SCALE,
          MODEL_SCALE,
          MODEL_SCALE,
        );
        softenMetal(background);
        removeFirstSectionPile(background);
        background.traverse((child) => {
          const match = /^FW_Signal_Lamp_(\d)$/.exec(child.name);
          if (!match || !(child instanceof THREE.Mesh)) return;
          // 램프마다 색이 달라야 하므로 재질을 따로 복제한다.
          const material = (
            child.material as THREE.MeshStandardMaterial
          ).clone();
          child.material = material;
          // 조명이 약해도 멀리서 보이도록 램프 중심에 색 후광(조명·톤매핑 영향 없음)을 겹친다.
          gltf.scene.updateMatrixWorld(true);
          const box = new THREE.Box3().setFromObject(child);
          const halo = new THREE.Sprite(
            new THREE.SpriteMaterial({
              map: haloTexture,
              color: SIGNAL_COLOR.normal,
              transparent: true,
              depthWrite: false,
              blending: THREE.AdditiveBlending,
              toneMapped: false,
            }),
          );
          halo.position.copy(box.getCenter(new THREE.Vector3()));
          halo.scale.setScalar(
            Math.max(...box.getSize(new THREE.Vector3()).toArray()) *
              HALO_SCALE,
          );
          scene.add(halo);
          signals.push({
            material,
            column: SIGNAL_COLUMN[Number(match[1])],
            halo,
          });
        });
        scene.add(background);
      });
    new GLTFLoader().setDRACOLoader(draco).load(
      "/models/MachineConveyorBelt.glb",
      (gltf) => {
        if (disposed) {
          disposeModel(gltf.scene);
          return;
        }
        // 모델은 Blender에서 0.01 배로 줄여 내보냈다. 화면에서 더 크게 보이도록 MODEL_SCALE만큼 키운다.
        model = gltf.scene;
        model.scale.set(MODEL_MIRROR * MODEL_SCALE, MODEL_SCALE, MODEL_SCALE);
        model.traverse((child) => {
          if (!(child instanceof THREE.Mesh)) return;
          const materials = Array.isArray(child.material)
            ? child.material
            : [child.material];
          materials.forEach((material) => {
            if (
              !(material instanceof THREE.MeshStandardMaterial) ||
              material.name !== BELT_MATERIAL
            )
              return;
            [
              material.map,
              material.normalMap,
              material.metalnessMap,
              material.roughnessMap,
            ].forEach((texture) => {
              if (
                !texture ||
                beltTextures.some((item) => item.texture === texture)
              )
                return;
              texture.wrapS = THREE.RepeatWrapping;
              beltTextures.push({ texture, base: texture.offset.x });
            });
          });
        });
        softenMetal(model);
        scene.add(model);
        mixer = new THREE.AnimationMixer(model);
        if (gltf.animations[0]) mixer.clipAction(gltf.animations[0]).play();
        mixer.update(0);
        model.updateMatrixWorld(true);
        const boxObjects: THREE.Object3D[] = [];
        model.traverse((child) => {
          if (BOX_NAME.test(child.name)) boxObjects.push(child);
        });
        boxObjects.sort((a, b) => a.name.localeCompare(b.name));
        boxObjects.forEach((object, index) => {
          const world = object.getWorldPosition(new THREE.Vector3());
          boxes.push({
            object,
            y: world.y,
            z: world.z,
            offset: index / boxObjects.length,
          });
        });
        // 지나가는 상자에 마커가 붙지 않도록 상자는 마커 위치 찾기에서 뺀다.
        const isBox = (object: THREE.Object3D | null) => {
          for (; object; object = object.parent)
            if (BOX_NAME.test(object.name)) return true;
          return false;
        };
        hotspots.forEach((hotspot) => {
          const referenceCamera = camera.clone();
          referenceCamera.aspect = 1512 / 834;
          if (hotspot.id === "right") {
            referenceCamera.position.set(9.42, 2, 0.5);
            referenceCamera.lookAt(controls.target);
          }
          referenceCamera.updateProjectionMatrix();
          referenceCamera.updateMatrixWorld(true);
          raycaster.near = 0;
          raycaster.far = Infinity;
          raycaster.setFromCamera(
            new THREE.Vector2(...hotspot.point),
            referenceCamera,
          );
          const hit = raycaster
            .intersectObject(model!, true)
            .find((item) => !isBox(item.object));
          if (hit) {
            const anchor = new THREE.Object3D();
            anchor.position.copy(hit.object.worldToLocal(hit.point.clone()));
            hit.object.add(anchor);
            anchors.push({ anchor, id: hotspot.id });
          }
        });
        setStatus("");
      },
      undefined,
      () => {
        if (!disposed) setStatus("모델을 불러오지 못했습니다.");
      },
    );
    const clock = new THREE.Clock();
    renderer.setAnimationLoop(() => {
      // 일시정지 중에는 시간을 0으로 두어 컨베이어·상자·벨트만 멈추고, 화면 회전·센서 표시는 유지한다.
      const delta = pausedRef.current ? 0 : clock.getDelta();
      if (pausedRef.current) clock.getDelta();
      mixer?.update(delta);
      // 신호등: 칸마다 센서 중 가장 나쁜 판정(정상/주의/경고)의 색으로 켠다. 경고는 깜빡인다.
      const latest = samplesRef.current.at(-1);
      if (signals.length > 0) {
        if (latest !== signalKey) {
          signalKey = latest;
          signals.forEach((signal) => {
            const fields = BUBBLE_INFO[signal.column]?.fields ?? [];
            const levels = fields.map((field) =>
              sensorLevel(field, sensorValue(latest?.record, field)),
            );
            const level: SensorLevel = levels.includes("warning")
              ? "warning"
              : levels.includes("caution")
                ? "caution"
                : "normal";
            // 겉면 색을 어둡게 해야 조명에 하얗게 씻기지 않고 발광색이 살아 있다.
            signal.material.color.set(SIGNAL_COLOR[level]).multiplyScalar(0.3);
            signal.material.emissive.set(SIGNAL_COLOR[level]);
            signal.material.userData.level = level;
            signal.halo.material.color.set(SIGNAL_COLOR[level]);
          });
        }
        // 주의·경고는 깜빡인다(주의는 느리게, 경고는 빠르게). 정상은 항상 켜져 있다.
        signals.forEach(({ material, halo }) => {
          const level = material.userData.level as SensorLevel;
          const speed = level === "warning" ? 9 : 4;
          const blink = pausedRef.current
            ? 1
            : 0.55 + 0.45 * Math.sin(clock.elapsedTime * speed);
          const factor = level === "normal" ? 1 : blink;
          material.emissiveIntensity = SIGNAL_INTENSITY * factor;
          halo.material.opacity = HALO_OPACITY * factor;
        });
      }
      beltPhase = (beltPhase + delta / BELT_LOOP_SECONDS) % 1;
      beltTextures.forEach(({ texture, base }) => {
        texture.offset.x = base + BELT_DIRECTION * beltPhase;
      });
      if (boxes.length > 0) {
        const [start, end] = BOX_X_RANGE;
        // 벨트 윗면이 움직이는 속도와 같게 맞춘다(한 번 지나가는 데 걸리는 시간 = 구간 길이 / 속도).
        boxPhase =
          (boxPhase +
            (delta * BELT_TRAVEL_PER_LOOP) /
              ((end - start) * BELT_LOOP_SECONDS)) %
          1;
        boxes.forEach(({ object, y, z, offset }) => {
          const t = (boxPhase + offset) % 1;
          const x =
            (BELT_DIRECTION > 0
              ? start + t * (end - start)
              : end - t * (end - start)) *
            MODEL_SCALE *
            MODEL_MIRROR;
          object.parent?.updateWorldMatrix(true, false);
          object.position.copy(
            object.parent?.worldToLocal(new THREE.Vector3(x, y, z)) ??
              new THREE.Vector3(x, y, z),
          );
        });
      }
      controls.update();
      model?.updateMatrixWorld(true);
      camera.updateMatrixWorld();
      anchors.forEach(({ anchor, id }) => {
        const marker = markerRefs.current[id];
        if (!marker || !model) return;
        anchor.getWorldPosition(world);
        screen.copy(world).project(camera);
        const inView =
          screen.z >= -1 &&
          screen.z <= 1 &&
          Math.abs(screen.x) <= 1 &&
          Math.abs(screen.y) <= 1;
        let visible = false;
        if (inView) {
          const distance = camera.position.distanceTo(world);
          raycaster.set(
            camera.position,
            world.clone().sub(camera.position).normalize(),
          );
          raycaster.near = camera.near;
          raycaster.far = Math.max(camera.near, distance - 0.015);
          visible = raycaster.intersectObject(model, true).length === 0;
        }
        marker.hidden = !visible;
        if (visible) {
          marker.style.left = `${(screen.x + 1) * 50}%`;
          marker.style.top = `${(1 - screen.y) * 50}%`;
          marker.dataset.side = screen.x > 0.35 ? "left" : "right";
        }
      });
      renderer.render(scene, camera);
    });
    return () => {
      disposed = true;
      observer.disconnect();
      renderer.setAnimationLoop(null);
      mixer?.stopAllAction();
      if (model) disposeModel(model);
      if (background) disposeModel(background);
      draco.dispose();
      swipeArea.removeEventListener("wheel", blockSwipeBack);
      swipeArea.removeEventListener("pointerenter", lockSwipeBack);
      swipeArea.removeEventListener("pointerleave", unlockSwipeBack);
      unlockSwipeBack();
      controls.dispose();
      renderer.dispose();
      // dispose만으로는 WebGL 컨텍스트와 GPU 메모리 반납이 미뤄져 페이지를 오갈수록 쌓이므로 즉시 반납한다.
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [paused, hasBackdrop]);

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
        <div className="model-viewer__canvas" ref={hostRef}>
          {hasBackdrop ? (
            backdrop
          ) : paused && (
            <img
              className="model-viewer__poster"
              src="/models/conveyor-poster.webp"
              alt=""
              draggable={false}
            />
          )}
        </div>
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
        {hotspots.map((hotspot) => (
          <div
            key={hotspot.id}
            ref={(node) => {
              markerRefs.current[hotspot.id] = node;
            }}
            className="dashboard-viewer__hotspot"
            hidden
            onKeyDown={(event) => {
              if (event.key === "Escape") setOpenDetail(null);
            }}
          >
            <button
              className="dashboard-viewer__marker"
              type="button"
              aria-label={`${hotspot.label} 상세 정보`}
              aria-expanded={openDetail === hotspot.id}
              onClick={() =>
                setOpenDetail((open) =>
                  open === hotspot.id ? null : hotspot.id,
                )
              }
            />
            {openDetail === hotspot.id && (
              <div
                className="dashboard-viewer__detail"
                role="region"
                aria-label={`${hotspot.label} 상세 정보`}
              >
                <div className="dashboard-viewer__detail-heading">
                  <strong>{hotspot.label}</strong>
                  <button
                    type="button"
                    className="dashboard-viewer__close"
                    aria-label="상세 정보 닫기"
                    onClick={() => setOpenDetail(null)}
                  >
                    ×
                  </button>
                </div>
                <p>3D 모델의 선택 지점입니다.</p>
                <p className="dashboard-viewer__detail-note">
                  상세 정보는 예시이며 실제 설비 데이터와 연결되어 있지
                  않습니다.
                </p>
              </div>
            )}
          </div>
        ))}
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
        {!hasBackdrop && !paused && status && <p className="model-viewer__status">{status}</p>}
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
