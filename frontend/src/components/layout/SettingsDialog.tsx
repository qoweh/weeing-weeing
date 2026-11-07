import {
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
} from "react";
import type { Settings } from "./settings";
import Button from "../ui/Button";
import ProfileAvatar from "./ProfileAvatar";
import useProfilePhoto from "./useProfilePhoto";
import "./SettingsDialog.css";

const tabs = ["화면", "알림", "계정"];
const zoomSteps = [80, 90, 100, 110, 120];

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className="settings-toggle"
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}

function ThemeCard({
  value,
  current,
  onSelect,
  label,
}: {
  value: string;
  current: string;
  onSelect: (value: string) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={current === value}
      className={`settings-theme settings-theme--${value}`}
      onClick={() => onSelect(value)}
    >
      <span className="settings-theme__preview" aria-hidden="true">
        <i />
        <b />
        <b />
      </span>
      <span className="settings-theme__label">
        <span className="settings-radio" aria-hidden="true" />
        {label}
      </span>
    </button>
  );
}

export default function SettingsDialog({
  user,
  theme,
  onToggleTheme,
  screenZoom,
  onChangeScreenZoom,
  defaultScreenZoom,
  onResetScreenZoom,
  sidebarCollapsed,
  onChangeSidebarCollapsed,
  settings,
  onChangeSettings,
  onLogout,
  busy,
  initialTab = "화면",
  onClose,
}: {
  user: { name: string; role: string; employee_no?: string };
  theme: string;
  onToggleTheme: () => void;
  screenZoom: number;
  onChangeScreenZoom: (zoom: number) => void;
  defaultScreenZoom: number;
  onResetScreenZoom: () => void;
  sidebarCollapsed: boolean;
  onChangeSidebarCollapsed: (collapsed: boolean) => void;
  settings: Settings;
  onChangeSettings: (settings: Settings) => void;
  onLogout: () => void;
  busy: boolean;
  initialTab?: string;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [tab, setTab] = useState(initialTab);
  const photoInput = useRef<HTMLInputElement>(null);
  const [photoError, setPhotoError] = useState("");
  const profile = useProfilePhoto(user.employee_no ?? "");

  async function choosePhoto(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (file) setPhotoError(await profile.change(file));
  }

  useEffect(() => {
    const element = dialog.current;
    const previousFocus = window.document.activeElement;
    if (element && !element.open) element.showModal();
    return () => {
      if (element?.open) element.close();
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, []);

  const update = (patch: Partial<Settings>) =>
    onChangeSettings({ ...settings, ...patch });
  const zoomPosition = ((screenZoom - 80) / 40) * 100;

  return (
    <dialog
      ref={dialog}
      className="settings-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <nav className="settings-dialog__nav" aria-label="설정 메뉴">
        <h2 id={titleId}>설정</h2>
        <div role="tablist" aria-orientation="vertical">
          {tabs.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              className="settings-dialog__tab"
              onClick={() => setTab(name)}
            >
              {name}
            </button>
          ))}
        </div>
      </nav>
      <section
        className="settings-dialog__content"
        role="tabpanel"
        aria-label={`${tab} 설정`}
      >
        <header>
          <h3>{tab}</h3>
          <button
            type="button"
            className="settings-dialog__close"
            aria-label="설정 닫기"
            onClick={onClose}
          >
            <svg viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path
                d="M1 1l12 12M13 1 1 13"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </header>
        <div className="settings-dialog__body">
          {tab === "화면" && (
            <>
              <h4>테마</h4>
              <p>화면 색상 모드를 선택합니다.</p>
              <div
                className="settings-themes"
                role="radiogroup"
                aria-label="테마"
              >
                <ThemeCard
                  value="light"
                  label="라이트"
                  current={theme}
                  onSelect={(value) => value !== theme && onToggleTheme()}
                />
                <ThemeCard
                  value="dark"
                  label="다크"
                  current={theme}
                  onSelect={(value) => value !== theme && onToggleTheme()}
                />
              </div>
              <div className="settings-row-head">
                <div>
                  <h4>화면 비율</h4>
                  <p>
                    헤더, 사이드바, 본문 전체의 크기를 조절합니다. (80% – 120%,
                    기본 {defaultScreenZoom}%)
                  </p>
                </div>
                <Button
                  onClick={onResetScreenZoom}
                  disabled={screenZoom === defaultScreenZoom}
                >
                  기본값으로
                </Button>
              </div>
              <div
                className="settings-zoom"
                style={
                  { "--zoom-position": `${zoomPosition}%` } as CSSProperties
                }
              >
                <output aria-live="polite">{screenZoom}%</output>
                <input
                  type="range"
                  min="80"
                  max="120"
                  step="10"
                  value={screenZoom}
                  aria-label="화면 비율"
                  onChange={(event) =>
                    onChangeScreenZoom(Number(event.target.value))
                  }
                />
                <ul aria-hidden="true">
                  {zoomSteps.map((step) => (
                    <li
                      key={step}
                      className={step === screenZoom ? "is-current" : ""}
                    >
                      {step}%
                    </li>
                  ))}
                </ul>
              </div>
              <h4 className="settings-section">챗봇 표시 방식</h4>
              <p>선택한 방식은 챗봇을 다음에 열 때 적용됩니다.</p>
              <div
                className="settings-segment"
                role="radiogroup"
                aria-label="챗봇 표시 방식"
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={settings.chatDisplay === "modal"}
                  onClick={() => update({ chatDisplay: "modal" })}
                >
                  모달
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={settings.chatDisplay === "drawer"}
                  onClick={() => update({ chatDisplay: "drawer" })}
                >
                  서랍
                </button>
              </div>
              <h4 className="settings-section">사이드 메뉴</h4>
              <ul className="settings-list settings-list--single">
                <li>
                  <div>
                    <strong>사이드 메뉴 접기</strong>
                    <small>
                      메뉴를 아이콘만 보이게 접어 본문을 더 넓게 씁니다.
                    </small>
                  </div>
                  <Toggle
                    checked={sidebarCollapsed}
                    label="사이드 메뉴 접기"
                    onChange={onChangeSidebarCollapsed}
                  />
                </li>
              </ul>
            </>
          )}
          {tab === "알림" && (
            <>
              <h4>알림 수신</h4>
              <p>헤더의 주의·경고 배지와 사건 목록에 반영됩니다.</p>
              <ul className="settings-list">
                {(
                  [
                    [
                      "notifyWarning",
                      "주의 알림",
                      "주의 단계 사건이 생기면 헤더 배지에 건수를 표시합니다.",
                    ],
                    [
                      "notifyError",
                      "경고 알림",
                      "경고 단계 사건이 생기면 헤더 배지와 사건 목록으로 알려줍니다.",
                    ],
                    [
                      "autoOpenError",
                      "새 경고 시 팝업 자동 열기",
                      "새 경고가 들어오면 사건 목록 팝업을 바로 엽니다.",
                    ],
                  ] as [
                    keyof Pick<
                      Settings,
                      "notifyWarning" | "notifyError" | "autoOpenError"
                    >,
                    string,
                    string,
                  ][]
                ).map(([key, title, description]) => (
                  <li key={key}>
                    <div>
                      <strong>{title}</strong>
                      <small>{description}</small>
                    </div>
                    <Toggle
                      checked={settings[key]}
                      label={title}
                      onChange={(checked) => update({ [key]: checked })}
                    />
                  </li>
                ))}
              </ul>
            </>
          )}
          {tab === "계정" && (
            <>
              <div className="settings-profile">
                <ProfileAvatar
                  user={{
                    name: user.name,
                    employee_no: user.employee_no ?? "",
                  }}
                  size={64}
                />
                <div>
                  <strong>{user.name}</strong>
                  <small>
                    {user.role}
                    {user.employee_no ? ` · 사번 ${user.employee_no}` : ""}
                  </small>
                  <div className="settings-profile__actions">
                    <button
                      type="button"
                      onClick={() => photoInput.current?.click()}
                    >
                      {profile.photo ? "사진 변경" : "사진 등록"}
                    </button>
                    {profile.photo && (
                      <button
                        type="button"
                        onClick={() => {
                          setPhotoError("");
                          profile.remove();
                        }}
                      >
                        삭제
                      </button>
                    )}
                  </div>
                  <input
                    ref={photoInput}
                    type="file"
                    hidden
                    accept="image/jpeg,image/png,image/webp"
                    onChange={choosePhoto}
                  />
                  {photoError && (
                    <p className="settings-profile__error" role="alert">
                      {photoError}
                    </p>
                  )}
                </div>
              </div>
              <div className="settings-session">
                <div>
                  <h4>로그인 세션</h4>
                  <p>이 기기에서 로그인 중입니다.</p>
                </div>
                <Button
                  className="settings-logout"
                  onClick={onLogout}
                  disabled={busy}
                >
                  로그아웃
                </Button>
              </div>
            </>
          )}
        </div>
        <footer>
          <Button onClick={onClose}>닫기</Button>
        </footer>
      </section>
    </dialog>
  );
}
