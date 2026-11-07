import * as THREE from "three";

// 원본 텍스처·UV가 없는 단색 재질(골판지, 배전함 도장, 검은 플라스틱)에 쓸 절차적 표면.
// 오브젝트 좌표로 만든 높이값을 화면 미분(dFdx/dFdy)으로 노말에 반영하고, 색에는 얼룩을 곱한다.
// UV가 없어도 되도록 셰이더 안에서 모두 계산한다.
export type SurfaceKind = "cardboard" | "paint" | "plastic" | "hull";

const COMMON = /* glsl */ `
float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash21(i), hash21(i + vec2(1.0, 0.0)), f.x),
    mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), f.x),
    f.y
  );
}
float vnoise3(vec3 p) {
  return 0.5 * (vnoise(p.xy + p.z * 7.31) + vnoise(p.yz + p.x * 5.17));
}
// 법선이 가장 큰 축을 뺀 두 좌표(바닥은 xz, 벽은 xy·zy). 오브젝트 좌표는 Y가 위쪽이다.
vec2 panelUV(vec3 p, vec3 n) {
  vec3 a = abs(n);
  if (a.y >= a.x && a.y >= a.z) return p.xz;
  if (a.x >= a.z) return p.zy;
  return p.xy;
}
// 80x40cm 철판 패널: x는 이음새까지의 거리(cm), yz는 패널 번호
vec3 panelCell(vec2 q) {
  q /= vec2(80.0, 40.0);
  float row = floor(q.y);
  q.x += 0.5 * mod(row, 2.0);
  vec2 cell = floor(q);
  vec2 f = fract(q);
  float edge = min(min(f.x, 1.0 - f.x) * 80.0, min(f.y, 1.0 - f.y) * 40.0);
  return vec3(edge, cell);
}
vec3 perturbSurface(vec3 surfPos, vec3 surfNorm, vec2 dHdxy, float faceDirection) {
  vec3 sigmaX = normalize(dFdx(surfPos));
  vec3 sigmaY = normalize(dFdy(surfPos));
  vec3 r1 = cross(sigmaY, surfNorm);
  vec3 r2 = cross(surfNorm, sigmaX);
  float det = dot(sigmaX, r1) * faceDirection;
  vec3 grad = sign(det) * (dHdxy.x * r1 + dHdxy.y * r2);
  return normalize(abs(det) * surfNorm - grad);
}
`;

const SURFACES: Record<
  SurfaceKind,
  { height: string; tint: string; bump: number }
> = {
  // 테란 선체: 철판 패널 이음새(홈) + 패널별 밝기 차이 + 넓은 얼룩 + 위에서 흐른 때 자국
  hull: {
    height:
      "vec3 c = panelCell(panelUV(p, n)); return -(1.0 - smoothstep(0.6, 2.2, c.x));",
    tint: `vec3 c = panelCell(panelUV(p, n));
      float seam = 1.0 - smoothstep(0.6, 2.2, c.x);
      float plate = 0.8 + 0.2 * hash21(c.yz + 3.7);
      float macro = mix(0.6, 1.15, smoothstep(0.3, 0.75, vnoise3(p * 0.006)));
      float drip = mix(1.0, 0.4, smoothstep(0.5, 0.8, vnoise(vec2((p.x + p.z) * 0.05, p.y * 0.002))));
      return vec3(plate * macro * drip * (1.0 - 0.5 * seam));`,
    bump: 0.5,
  },
  // 골(플루트) 줄무늬 + 종이 결 + 부분적인 색 얼룩
  cardboard: {
    height:
      "return 0.6 * sin(p.x * 1.6) + 0.12 * vnoise3(p * 2.5) + 0.06 * vnoise3(p * 9.0);",
    tint: "return vec3(0.93 + 0.14 * vnoise3(p * 0.35)) * (0.98 + 0.04 * vnoise3(p * 6.0));",
    bump: 0.45,
  },
  // 배전함 도장: 위아래로 긴 솔질 자국 + 잔 요철, 바닥 쪽이 더 어둡다
  paint: {
    height:
      "return 0.35 * vnoise(vec2(p.x + p.z, p.y * 14.0)) + 0.25 * vnoise3(p * 3.0);",
    tint: "return vec3(mix(0.7, 1.0, smoothstep(0.0, 40.0, p.y))) * (0.94 + 0.12 * vnoise3(p * 0.12));",
    bump: 0.2,
  },
  // 검은 플라스틱: 잔 알갱이
  plastic: {
    height: "return 0.5 * vnoise3(p * 4.0);",
    tint: "return vec3(0.9 + 0.2 * vnoise3(p * 0.5));",
    bump: 0.2,
  },
};

export function applySurface(
  material: THREE.MeshStandardMaterial,
  kind: SurfaceKind,
) {
  const surface = SURFACES[kind];
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        "#include <common>\nvarying vec3 vObjPos;\nvarying vec3 vObjN;",
      )
      .replace(
        "#include <begin_vertex>",
        "#include <begin_vertex>\nvObjPos = position;\nvObjN = normal;",
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
varying vec3 vObjPos;
varying vec3 vObjN;
${COMMON}
float surfaceHeight(vec3 p, vec3 n) { ${surface.height} }
vec3 surfaceTint(vec3 p, vec3 n) { ${surface.tint} }`,
      )
      .replace(
        "#include <color_fragment>",
        "#include <color_fragment>\ndiffuseColor.rgb *= surfaceTint(vObjPos, vObjN);",
      )
      .replace(
        "#include <normal_fragment_maps>",
        `#include <normal_fragment_maps>
float surfaceH = surfaceHeight(vObjPos, vObjN);
normal = perturbSurface(-vViewPosition, normal, vec2(dFdx(surfaceH), dFdy(surfaceH)) * ${surface.bump.toFixed(2)}, faceDirection);`,
      );
  };
  material.customProgramCacheKey = () => `surface-${kind}`;
  material.needsUpdate = true;
}
