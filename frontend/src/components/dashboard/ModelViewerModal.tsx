import { useEffect, useRef } from "react";
import ModelViewer from "./ModelViewer";

type Props = { open: boolean; onClose: () => void };

export default function ModelViewerModal({ open, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="model-viewer-modal"
      aria-label="3D 뷰어 확대"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      {open && (
        <>
          <button
            type="button"
            className="model-viewer-modal__close"
            aria-label="닫기"
            onClick={onClose}
          >
            ×
          </button>
          <ModelViewer />
        </>
      )}
    </dialog>
  );
}
