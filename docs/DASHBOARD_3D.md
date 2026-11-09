# 대시보드 3D 뷰어 (보관)

대시보드의 3D 영역은 현재 **CCTV 화면(iframe)** 으로 대체되어 있고, 3D 모델 뷰어는 쓰지 않는다.
3D가 다시 필요하면 아래 보관본과 자원을 쓴다.

## 지금 상태
- `frontend/src/views/DashboardPage.tsx`는 `ModelViewer`에 `backdrop={<CctvPanel />}`을 넘긴다.
- `frontend/src/components/dashboard/ModelViewer.tsx`는 CCTV 위에 올라가는 오버레이(구역 점멸, 클릭 말풍선, 센서 그래프)만 그린다. `three`를 import하지 않는다.
- 3D 영역 높이는 화면에 보이는 크기로 최대 370px이다(`DashboardPage.scss`).

## 보관된 3D 자원
| 자원 | 위치 |
|---|---|
| 3D 뷰어 전체 버전(렌더러·모델 로딩·조명·정지 포스터·오버레이 포함) | `frontend/src/components/dashboard/ModelViewer3D.tsx` (어디에서도 import하지 않음) |
| 표면 재질 | `frontend/src/components/dashboard/surfaceMaterials.ts` |
| 모델 | `frontend/public/models/MachineConveyorBelt.glb`, `FactoryBackground.glb` |
| 정지 시 보여 주는 포스터 | `frontend/public/models/conveyor-poster.webp` |
| draco 디코더 | `frontend/public/draco/` |
| 텍스처 | `frontend/public/textures/` |
| 포스터·상태 문구 스타일 | `frontend/src/views/DashboardPage.scss`의 `.model-viewer__poster`, `.model-viewer__status` |

`ModelViewer3D.tsx`는 3D를 켜던 마지막 `ModelViewer`를 그대로 보관한 것이다.
이후 `ModelViewer.tsx`의 오버레이(말풍선·그래프) 수정은 보관본에 반영되어 있지 않을 수 있다.

## 다시 쓰는 방법
1. `DashboardPage.tsx`에서 `ModelViewer` import를 `ModelViewer3D`로 바꾸고, `backdrop`을 넘기지 않는다
   (`backdrop`이 없어야 3D가 그려진다. 있으면 그 내용만 보여 준다).
2. 정지(포스터) 동작을 쓰려면 `paused={pauseModelAnimation || !visible}`를 같이 넘긴다.
   설정 화면의 "3D 움직임 멈추기"(`pauseModelAnimation`)가 이 값을 바꾼다.
3. `useEffect`가 `three`를 불러오므로 번들이 커진다. 다시 켠 뒤에는 모델·디코더 캐시 헤더
   (`next.config.mjs`의 `/models`, `/draco`)와 `THREE.Cache`가 켜져 있는지 확인한다.
4. 오버레이 코드가 `ModelViewer.tsx`와 갈라졌으므로, 한쪽 변경을 다른 쪽에 맞춰야 한다.

## 이 구조로 바꾼 이유
CCTV 모드에서도 `ModelViewer`가 `three`, `GLTFLoader`, `DRACOLoader`를 import해서 쓰지 않는 3D 라이브러리가
번들에 실렸다. 3D를 별도 파일로 분리해 대시보드 번들에서 뺐다.
