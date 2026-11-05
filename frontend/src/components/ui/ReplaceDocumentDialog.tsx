import { useEffect, useId, useRef } from "react";
import Button from "./Button";
import "./ReplaceDocumentDialog.css";

export default function ReplaceDocumentDialog({
  docId,
  existingVersions,
  newVersion,
  onCancel,
  onConfirm,
}: {
  docId: string;
  existingVersions: string[];
  newVersion: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const element = dialog.current;
    const previousFocus = window.document.activeElement;
    if (element && !element.open) element.showModal();
    cancelButton.current?.focus();
    return () => {
      if (element?.open) element.close();
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      className="replace-document-dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <h2 id={titleId}>기존 문서 버전이 있습니다</h2>
      <p className="replace-document-dialog__name">{docId}</p>
      <p id={descriptionId}>
        같은 문서 ID로 등록된 버전{" "}
        {existingVersions.map((item) => `v${item}`).join(", ")}이 있습니다. 새
        버전 v{newVersion}을 등록할까요?
      </p>
      <div className="replace-document-dialog__actions">
        <Button ref={cancelButton} type="button" onClick={onCancel}>
          취소
        </Button>
        <Button
          type="button"
          className="replace-document-dialog__confirm"
          onClick={onConfirm}
        >
          새 버전 등록
        </Button>
      </div>
    </dialog>
  );
}
