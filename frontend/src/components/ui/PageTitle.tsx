import type { ReactNode } from "react";
import "./ui.scss";

export default function PageTitle({ children }: { children: ReactNode }) {
  return <h1 className="page-title">{children}</h1>;
}
