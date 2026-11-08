import { useEffect, useState } from "react";
import "./CctvPanel.scss";

// CCTV 영상은 3D 모델·센서 데이터와 분리된 화면이다. CCTV 관련 변경(주소·재생 방식·표시 조건)은
// 이 파일에서만 하고, ModelViewer와 센서 데이터 흐름(samples)은 건드리지 않는다.
// 주소를 바꾸면 next.config.mjs의 frame-src(CSP)도 함께 고친다.
const CCTV_URL = "http://127.0.0.1:18080/viewer.html";

// 주소에 ?cctv=1이 있을 때만 CCTV를 보여 준다. 서버 렌더링에서는 항상 false라 첫 렌더가 어긋나지 않는다.
export function useCctvMode() {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    setEnabled(new URLSearchParams(window.location.search).get("cctv") === "1");
  }, []);
  return enabled;
}

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
