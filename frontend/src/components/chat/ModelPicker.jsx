import { useEffect, useRef, useState } from "react";

// 네이티브 <select> 대신 테마에 맞춘 드롭다운. 목록은 입력창 위로 펼쳐진다.
export default function ModelPicker({ models, value, onChange, disabled }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef(null);
  const button = useRef(null);
  const selectedIndex = Math.max(
    0,
    models.findIndex((m) => m.id === value),
  );

  useEffect(() => {
    if (!open) return undefined;
    function onPointerDown(event) {
      if (!root.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  function toggle() {
    setActive(selectedIndex);
    setOpen((current) => !current);
  }
  function choose(index) {
    onChange(models[index].id);
    setOpen(false);
    button.current?.focus();
  }
  function onKeyDown(event) {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      button.current?.focus();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setActive(selectedIndex);
        setOpen(true);
        return;
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((index) => (index + step + models.length) % models.length);
    } else if ((event.key === "Enter" || event.key === " ") && open) {
      event.preventDefault();
      choose(active);
    }
  }

  return (
    <div className="chat-model-picker" ref={root} onKeyDown={onKeyDown}>
      <button
        ref={button}
        type="button"
        className="chat-dialog__model"
        aria-label="Claude 모델 선택"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={toggle}
      >
        {models[selectedIndex].label}
      </button>
      {open && (
        <ul
          className="chat-model-picker__list"
          role="listbox"
          aria-label="Claude 모델"
        >
          {models.map((model, index) => (
            <li
              key={model.id}
              role="option"
              aria-selected={model.id === value}
              className={`chat-model-picker__option${index === active ? " is-active" : ""}${model.id === value ? " is-selected" : ""}`}
              onPointerEnter={() => setActive(index)}
              onClick={() => choose(index)}
            >
              {model.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
