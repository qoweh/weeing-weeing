import { useCallback, useSyncExternalStore } from "react";

// 서버에 프로필 사진 저장 API가 아직 없어, 이 브라우저(localStorage)에 사번별로 저장한다.
const keyOf = (employeeNo: string) => `weeing-profile-photo:${employeeNo}`;
const changed = "weeing-profile-photo-changed";
const allowed = ["image/jpeg", "image/png", "image/webp"];
const maxBytes = 5 * 1024 * 1024;
const outputSize = 192;

function read(employeeNo: string) {
  try {
    return localStorage.getItem(keyOf(employeeNo)) || "";
  } catch {
    return "";
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener(changed, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(changed, onChange);
    window.removeEventListener("storage", onChange);
  };
}

// 가운데를 정사각형으로 잘라 192px로 줄인 JPEG 데이터 URL을 만든다.
async function toAvatar(file: File) {
  const bitmap = await createImageBitmap(file);
  try {
    const side = Math.min(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = outputSize;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("이미지를 처리하지 못했습니다.");
    context.drawImage(
      bitmap,
      (bitmap.width - side) / 2,
      (bitmap.height - side) / 2,
      side,
      side,
      0,
      0,
      outputSize,
      outputSize,
    );
    return canvas.toDataURL("image/jpeg", 0.85);
  } finally {
    bitmap.close();
  }
}

export default function useProfilePhoto(employeeNo: string) {
  const photo = useSyncExternalStore(
    subscribe,
    () => read(employeeNo),
    () => "",
  );

  /** 성공하면 빈 문자열, 실패하면 안내 문구를 돌려준다. */
  const change = useCallback(
    async (file: File) => {
      if (!allowed.includes(file.type))
        return "JPG, PNG, WebP 이미지를 선택하세요.";
      if (file.size > maxBytes) return "5MB 이하 이미지를 선택하세요.";
      try {
        localStorage.setItem(keyOf(employeeNo), await toAvatar(file));
        window.dispatchEvent(new Event(changed));
        return "";
      } catch {
        return "사진을 저장하지 못했습니다. 다른 이미지로 시도해 주세요.";
      }
    },
    [employeeNo],
  );

  const remove = useCallback(() => {
    try {
      localStorage.removeItem(keyOf(employeeNo));
    } catch {
      /* 저장소를 쓸 수 없으면 지울 것도 없다 */
    }
    window.dispatchEvent(new Event(changed));
  }, [employeeNo]);

  return { photo, change, remove };
}
