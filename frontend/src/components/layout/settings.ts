import { createContext } from "react";

export type Settings = {
  notifyWarning: boolean;
  notifyError: boolean;
  autoOpenError: boolean;
  refreshInterval: number;
  chatDisplay: "modal" | "drawer";
  pauseModelAnimation: boolean;
};

const storageKey = "weeing-settings";

export const refreshIntervals = [
  { value: 500, label: "0.5초" },
  { value: 1000, label: "1초" },
  { value: 5000, label: "5초" },
  { value: 30000, label: "30초" },
  { value: 60000, label: "1분" },
  { value: 300000, label: "5분" },
];

export const defaultSettings: Settings = {
  notifyWarning: true,
  notifyError: true,
  autoOpenError: false,
  refreshInterval: 1000,
  chatDisplay: "modal",
  pauseModelAnimation: false,
};

export const SettingsContext = createContext<Settings>(defaultSettings);

// 설정은 이 브라우저에만 저장한다. 저장소를 쓸 수 없으면 기본값으로 동작한다.
export function readSettings(): Settings {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    const interval = refreshIntervals.some(
      (item) => item.value === saved.refreshInterval,
    )
      ? saved.refreshInterval
      : defaultSettings.refreshInterval;
    return {
      notifyWarning: saved.notifyWarning ?? defaultSettings.notifyWarning,
      notifyError: saved.notifyError ?? defaultSettings.notifyError,
      autoOpenError: saved.autoOpenError ?? defaultSettings.autoOpenError,
      refreshInterval: interval,
      chatDisplay: saved.chatDisplay === "drawer" ? "drawer" : "modal",
      pauseModelAnimation: saved.pauseModelAnimation === true,
    };
  } catch {
    return defaultSettings;
  }
}

export function saveSettings(settings: Settings) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(settings));
  } catch {
    /* Storage may be unavailable. */
  }
}
