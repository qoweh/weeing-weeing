import "./model-hotspots.scss";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { Sky } from "three/addons/objects/Sky.js";

const hotspots = [
  { id: "front", label: "정면 표시 지점", point: [-0.094, 0.12] },
  { id: "right", label: "우측면 표시 지점", point: [0.022, -0.067] },
] as const;

type Props = { paused?: boolean; onExpand?: () => void };

export default function ModelViewer({ paused = false, onExpand }: Props) {
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
      <div className="model-viewer__stage">
        <div className="model-viewer__canvas" ref={hostRef} />
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
