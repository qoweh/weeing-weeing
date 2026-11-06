import type { ReactNode } from "react";

export type HomeTone = "danger" | "warning" | "success" | "info" | "neutral";

export function HomeBadge({
  tone = "neutral",
  children,
}: {
  tone?: HomeTone;
  children: ReactNode;
}) {
  return <span className={`home-badge home-badge--${tone}`}>{children}</span>;
}

/** 메인 대시보드의 박스 공통 틀: 제목·설명·우측 보조 영역·본문 */
export default function HomeCard({
  id,
  title,
  description,
  aside,
  className = "",
  children,
}: {
  id: string;
  title: string;
  description?: string;
  aside?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`home-card ${className}`} aria-labelledby={id}>
      <header className="home-card__head">
        <div>
          <h2 id={id}>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}

export function HomeNotice({
  children,
  action,
  tone = "neutral",
}: {
  children: ReactNode;
  action?: ReactNode;
  tone?: "neutral" | "danger";
}) {
  return (
    <p className={`home-notice home-notice--${tone}`} role="status">
      <span>{children}</span>
      {action}
    </p>
  );
}
