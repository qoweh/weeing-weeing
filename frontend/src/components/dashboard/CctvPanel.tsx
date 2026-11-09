import "./CctvPanel.scss";

// CCTV 영상은 3D 모델·센서 데이터와 분리된 화면이다. CCTV 관련 변경(주소·재생 방식·표시 조건)은
// 이 파일에서만 하고, ModelViewer와 센서 데이터 흐름(samples)은 건드리지 않는다.
const CCTV_URL = "/cctv-viewer";

// active가 false(대시보드가 숨겨진 상태)면 영상 연결을 끊어 백그라운드에서 스트림을 받지 않게 한다.
export default function CctvPanel({ active = true }: { active?: boolean }) {
  return (
    <iframe
      title="실시간 CCTV"
      src={active ? CCTV_URL : "about:blank"}
      allow="autoplay"
      scrolling="no"
      className="cctv-panel"
    />
  );
}
