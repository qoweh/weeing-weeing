import type { ComponentType } from "react";
declare const ChatWidget: ComponentType<{
  screenZoom?: number;
  displayMode?: "modal" | "drawer";
  onSessionExpired: () => void;
}>;
export default ChatWidget;
