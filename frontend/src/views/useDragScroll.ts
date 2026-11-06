import { useEffect, type RefObject } from "react";

// 마우스로 가로 스크롤 영역을 드래그하면 그 방향으로 스크롤한다.
// 터치는 브라우저 기본 스크롤을 그대로 쓴다.
export default function useDragScroll(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let startX = 0;
    let startLeft = 0;
    let dragging = false;
    let moved = false;

    function onDown(event: PointerEvent) {
      if (event.pointerType !== "mouse" || event.button !== 0) return;
      dragging = true;
      moved = false;
      startX = event.clientX;
      startLeft = el!.scrollLeft;
    }
    function onMove(event: PointerEvent) {
      if (!dragging) return;
      const dx = event.clientX - startX;
      if (!moved && Math.abs(dx) < 4) return;
      if (!moved) {
        moved = true;
        el!.setPointerCapture(event.pointerId);
        el!.classList.add("is-dragging");
      }
      el!.scrollLeft = startLeft - dx;
    }
    function onUp(event: PointerEvent) {
      if (!dragging) return;
      dragging = false;
      if (moved && el!.hasPointerCapture(event.pointerId))
        el!.releasePointerCapture(event.pointerId);
      el!.classList.remove("is-dragging");
    }
    function onClickCapture(event: MouseEvent) {
      if (moved) {
        event.stopPropagation();
        event.preventDefault();
        moved = false;
      }
    }

    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("click", onClickCapture, true);
    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      el.removeEventListener("click", onClickCapture, true);
    };
  }, [ref]);
}
