import { useEffect, useRef, useState } from "react";

// three.js 예제 webgpu_loader_gltf를 그대로 옮긴 뷰어.
// 비상업 시연용이며 모델은 KhronosGroup glTF-Sample-Assets에서 불러온다.
const MODEL_ROOT =
  "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models";
const FETCH_TIMEOUT_MS = 10000;
const MAX_FPS = 60;
const FRAME_INTERVAL_MS = 1000 / MAX_FPS;

type ModelInfo = { name: string; variants: Record<string, string> };

type Props = {
  /** true이면 렌더링을 멈춘다(확대 모달이 열려 있을 때 등). */
  paused?: boolean;
  /** 주어지면 우측 하단에 확장 아이콘을 보여준다. */
  onExpand?: () => void;
};

export default function ModelViewer({ paused = false, onExpand }: Props) {
  const pausedRef = useRef(paused);
  const hostRef = useRef<HTMLDivElement>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selected, setSelected] = useState("DamagedHelmet");
  const [blur, setBlur] = useState(0);
  const [status, setStatus] = useState("불러오는 중입니다.");
  const api = useRef<{
    load: (m: ModelInfo) => void;
    setBlur: (v: number) => void;
    resume: () => void;
  } | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let cleanup = () => {};

    (async () => {
      try {
        if (!("gpu" in navigator)) throw new Error("WebGPU 미지원");
        const THREE = await import("three/webgpu");
        const { UltraHDRLoader } =
          await import("three/addons/loaders/UltraHDRLoader.js");
        const { OrbitControls } =
          await import("three/addons/controls/OrbitControls.js");
        const { GLTFLoader } =
          await import("three/addons/loaders/GLTFLoader.js");
        if (disposed) return;

        const camera = new THREE.PerspectiveCamera(45, 1, 0.25, 20);
        camera.position.set(-1.8, 0.6, 2.7);
        const scene = new THREE.Scene();
        const renderer = new THREE.WebGPURenderer({ antialias: true });
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        await renderer.init();
        if (disposed) {
          renderer.dispose();
          return;
        }
        host.appendChild(renderer.domElement);
        renderer.domElement.style.cssText =
          "display:block;width:100%;height:100%";

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.target.set(0, 0, -0.2);
        controls.update();

        const resize = () => {
          const { clientWidth: w, clientHeight: h } = host;
          if (!w || !h) return;
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
          renderer.setSize(w, h, false);
        };
        const observer = new ResizeObserver(resize);
        observer.observe(host);
        resize();

        new UltraHDRLoader()
          .setPath("/textures/equirectangular/")
          .load("royal_esplanade_2k.hdr.jpg", (texture: any) => {
            texture.mapping = THREE.EquirectangularReflectionMapping;
            scene.background = texture;
            scene.environment = texture;
          });

        let currentModel: any = null;
        let mixer: any = null;
        let loadId = 0;

        const fit = (object: any, fitOffset = 1.3) => {
          const box = new THREE.Box3().setFromObject(object);
          const size = box.getSize(new THREE.Vector3());
          const center = box.getCenter(new THREE.Vector3());
          const maxSize = Math.max(size.x, size.y, size.z);
          const dist =
            fitOffset *
            (maxSize / (2 * Math.tan((Math.PI * camera.fov) / 360)));
          const dir = controls.target
            .clone()
            .sub(camera.position)
            .normalize()
            .multiplyScalar(dist);
          controls.maxDistance = dist * 10;
          controls.minDistance = dist / 10;
          controls.target.copy(center);
          camera.near = dist / 100;
          camera.far = dist * 100;
          camera.updateProjectionMatrix();
          camera.position.copy(controls.target).sub(dir);
          controls.update();
        };

        const load = (info: ModelInfo) => {
          const variant = info.variants["glTF-Binary"] || info.variants["glTF"];
          if (!variant) return;
          const url = `${MODEL_ROOT}/${info.name}/${
            variant.endsWith(".glb") ? "glTF-Binary" : "glTF"
          }/${variant}`;
          if (currentModel) {
            currentModel.traverse((m: any) => {
              if (!m.isMesh) return;
              m.geometry.dispose();
              for (const v of Object.values(m.material) as any[]) {
                if (v && v.isTexture) v.dispose();
              }
              m.material.dispose();
            });
            scene.remove(currentModel);
            currentModel = null;
          }
          if (mixer) {
            mixer.stopAllAction();
            mixer = null;
          }
          const id = ++loadId;
          setStatus("모델을 불러오는 중입니다.");
          new GLTFLoader().load(
            url,
            async (gltf: any) => {
              if (id !== loadId || disposed) return;
              currentModel = gltf.scene;
              await renderer.compileAsync(currentModel, camera, scene);
              if (id !== loadId || disposed) return;
              scene.add(currentModel);
              fit(currentModel);
              if (gltf.animations.length > 0) {
                mixer = new THREE.AnimationMixer(currentModel);
                for (const clip of gltf.animations)
                  mixer.clipAction(clip).play();
              }
              setStatus("");
            },
            undefined,
            () => id === loadId && setStatus("모델을 불러오지 못했습니다."),
          );
        };

        const timer = new THREE.Timer();
        let lastFrame = 0;
        renderer.setAnimationLoop((now: number) => {
          // 고주사율 화면에서도 최대 MAX_FPS로 제한한다(1ms는 타이머 오차 허용).
          if (pausedRef.current) return;
          if (now - lastFrame < FRAME_INTERVAL_MS - 1) return;
          lastFrame = now;
          timer.update();
          controls.update();
          if (mixer) mixer.update(timer.getDelta());
          renderer.render(scene, camera);
        });

        api.current = {
          load,
          resume: () => {
            lastFrame = 0;
            timer.reset();
          },
          setBlur: (v) => {
            (scene as any).backgroundBlurriness = v;
          },
        };

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
        const list: ModelInfo[] = await fetch(
          `${MODEL_ROOT}/model-index.json`,
          {
            signal: controller.signal,
          },
        )
          .then((r) => {
            if (!r.ok) throw new Error(String(r.status));
            return r.json();
          })
          .finally(() => clearTimeout(timeout));
        if (disposed) return;
        setModels(list);
        const initial = list.find((m) => m.name === "DamagedHelmet") || list[0];
        if (initial) {
          setSelected(initial.name);
          load(initial);
        }

        cleanup = () => {
          observer.disconnect();
          renderer.setAnimationLoop(null);
          controls.dispose();
          renderer.dispose();
          renderer.domElement.remove();
        };
      } catch (error) {
        if (!disposed) {
          setStatus(
            (error as Error).message === "WebGPU 미지원"
              ? "이 브라우저는 WebGPU를 지원하지 않습니다."
              : "3D 뷰어를 불러오지 못했습니다.",
          );
        }
      }
    })();

    return () => {
      disposed = true;
      api.current = null;
      cleanup();
    };
  }, []);

  useEffect(() => {
    const wasPaused = pausedRef.current;
    pausedRef.current = paused;
    if (wasPaused && !paused) api.current?.resume();
  }, [paused]);

  return (
    <div className="model-viewer">
      <div className="model-viewer__bar">
        <label>
          모델
          <select
            value={selected}
            disabled={!models.length}
            onChange={(event) => {
              setSelected(event.target.value);
              const info = models.find((m) => m.name === event.target.value);
              if (info) api.current?.load(info);
            }}
          >
            {models.length === 0 && <option>{selected}</option>}
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          배경 흐림
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={blur}
            onChange={(event) => {
              const v = Number(event.target.value);
              setBlur(v);
              api.current?.setBlur(v);
            }}
          />
        </label>
      </div>
      <div className="model-viewer__stage">
        <div className="model-viewer__canvas" ref={hostRef} />
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
