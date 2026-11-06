import "./model-hotspots.scss";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { Sky } from "three/addons/objects/Sky.js";
import {
  formatSensor,
  sensorCharts,
  sensorPath,
  sensorValue,
  type SensorSample,
} from "../../views/telemetryCharts";

const hotspots = [
  { id: "front", label: "정면 표시 지점", point: [-0.094, 0.12] },
  { id: "right", label: "우측면 표시 지점", point: [0.022, -0.067] },
] as const;

type Props = {
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
  // 그래프 위에 마우스를 올리면 그 시점의 값을 보여준다(x: 0~600 그래프 좌표).
  const [hoverX, setHoverX] = useState<number | null>(null);
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
  const shown = hover ? hover.value : latest;

  return (
    <section
      className={`model-viewer__graph-box${level === "normal" ? "" : ` model-viewer__graph-box--${level}`}`}
      aria-label={`${chart.title} 센서 그래프${LEVEL_LABEL[level]}`}
    >
      <p className="model-viewer__bubble-title">
        {chart.title}
        {chart.unit && ` [${chart.unit}]`}
        <b>{formatSensor(shown, chart.digits)}</b>
      </p>
      <div
        className="model-viewer__bubble-plot"
        onPointerMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          if (rect.width > 0)
            setHoverX(
              Math.min(
                600,
                Math.max(0, ((event.clientX - rect.left) / rect.width) * 600),
              ),
            );
        }}
        onPointerLeave={() => setHoverX(null)}
      >
        <svg
          viewBox="0 0 600 80"
          preserveAspectRatio="none"
          role="img"
          aria-label={`${chart.title}의 최근 수신 추이`}
        >
          <path d="M0 16H600 M0 45H600 M0 74H600" className="grid" />
          {ready && <path d={path} className="line" />}
          {hover && hoverX !== null && (
            <path d={`M${hoverX} 0V80`} className="cursor" />
          )}
        </svg>
        {hover && (
          <span className="model-viewer__bubble-hover">
            {hover.secondsAgo === 0 ? "현재" : `${hover.secondsAgo}초 전`}
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

type Column = 1 | 2 | 3;

// 눌린 상자를 뺀 나머지 상자 영역에 말풍선을 채운다.
// 1번·3번이면 붙어 있는 두 상자에 하나, 2번이면 3번 상자 영역에 하나.
function bubblesFor(active: Column) {
  const fields = BUBBLE_INFO[active]?.fields ?? BUBBLE_FIELDS;
  if (active === 1)
    return [{ from: 2, to: 3, tail: "left", fields, row: false }];
  if (active === 3)
    return [{ from: 1, to: 2, tail: "right", fields, row: false }];
  // 가운데 상자는 오른쪽 상자 영역에 말풍선 하나를 띄운다.
  return [{ from: 3, to: 3, tail: "left", fields, row: false }];
}

function GraphBubble({
  from,
  to,
  tail,
  fields,
  row,
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
          ? { left: `calc(${(from - 1) / 3} * 100% + 22px)` }
          : { right: `calc(${(3 - to) / 3} * 100% + 22px)` }),
        width: `min(340px, calc(${(to - from + 1) / 3} * 100% - 44px))`,
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
        <div
          className={`model-viewer__graph-boxes${row ? "" : " model-viewer__graph-boxes--stack"}`}
        >
          {fields.map((field) => (
            <GraphBox key={field} field={field} samples={samples} />
          ))}
        </div>
      </div>
    </div>
  );
}

export default function ModelViewer({
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
  const [status, setStatus] = useState("모델을 불러오는 중입니다.");
  pausedRef.current = paused;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setStatus("3D 뷰어를 불러오지 못했습니다.");
      return;
    }
    let disposed = false;
    let model: THREE.Group | undefined;
    let mixer: THREE.AnimationMixer | undefined;
    const anchors: { anchor: THREE.Object3D; id: string }[] = [];
    const raycaster = new THREE.Raycaster();
    const world = new THREE.Vector3();
    const screen = new THREE.Vector3();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const sky = new Sky();
    sky.scale.setScalar(10000);
    sky.material.uniforms.turbidity.value = 0;
    sky.material.uniforms.rayleigh.value = 3;
    sky.material.uniforms.mieDirectionalG.value = 0.7;
    sky.material.uniforms.sunPosition.value.set(-0.8, 0.19, 0.56);
    scene.add(sky);
    const pmrem = new THREE.PMREMGenerator(renderer);
    const environment = pmrem.fromScene(scene);
    scene.environment = environment.texture;
    const camera = new THREE.PerspectiveCamera(40, 1, 1, 100);
    camera.position.set(5, 2, 8);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 0.7, 0);
    controls.update();
    const resize = () => {
      if (!host.clientWidth || !host.clientHeight) return;
      camera.aspect = host.clientWidth / host.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(host.clientWidth, host.clientHeight);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();
    const draco = new DRACOLoader();
    draco.setDecoderPath("/draco/");
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
    new GLTFLoader().setDRACOLoader(draco).load(
      "/models/LittlestTokyo.glb",
      (gltf) => {
        if (disposed) {
          disposeModel(gltf.scene);
          return;
        }
        model = gltf.scene;
        model.position.set(1, 1, 0);
        model.scale.setScalar(0.01);
        scene.add(model);
        mixer = new THREE.AnimationMixer(model);
        if (gltf.animations[0]) mixer.clipAction(gltf.animations[0]).play();
        mixer.update(0);
        model.updateMatrixWorld(true);
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
          const hit = raycaster.intersectObject(model!, true)[0];
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
      const delta = clock.getDelta();
      if (pausedRef.current) return;
      mixer?.update(delta);
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
      draco.dispose();
      controls.dispose();
      environment.dispose();
      pmrem.dispose();
      sky.geometry.dispose();
      sky.material.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

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
        <div className="model-viewer__canvas" ref={hostRef} />
        <div className="model-viewer__frames" aria-hidden="true">
          <div className="model-viewer__frame" />
          <div className="model-viewer__frame" />
          <div className="model-viewer__frame" />
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
              samples={samples}
              title={BUBBLE_INFO[bubbleColumn]?.title ?? "센서 실시간 추이"}
              note={BUBBLE_INFO[bubbleColumn]?.note}
              description={BUBBLE_INFO[bubbleColumn]?.description}
              errorMessage={errorMessage}
              onClose={() => setBubbleColumn(null)}
            />
          ))}
        {status && <p className="model-viewer__status">{status}</p>}
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
