import "./CctvPanel.scss";

// CCTV 영상은 3D 모델·센서 데이터와 분리된 화면이다. CCTV 관련 변경(주소·재생 방식·표시 조건)은
// 이 파일에서만 하고, ModelViewer와 센서 데이터 흐름(samples)은 건드리지 않는다.
const CCTV_URL = "/cctv-viewer";

export default function CctvPanel() {
  return (
    <iframe
      title="실시간 CCTV"
      src={CCTV_URL}
      allow="autoplay"
      className="cctv-panel"
    />
  );
}
