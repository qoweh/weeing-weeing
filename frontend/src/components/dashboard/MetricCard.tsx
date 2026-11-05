import type { ReactNode } from "react";
import Card from "../ui/Card";
import Badge from "../ui/Badge";
export default function MetricCard({
  title,
  value,
  unit,
  note,
  tone,
  icon,
}: {
  title: ReactNode;
  value: ReactNode;
  unit: ReactNode;
  note: ReactNode;
  tone: string;
  icon: ReactNode;
}) {
  return (
    <Card className="metric">
      <div className="metric__heading">
        <h2>{title}</h2>
        <span className="metric__icon" aria-hidden="true">
          {icon}
        </span>
      </div>
      <div className="metric__value">
        {value}
        <span>{unit}</span>
      </div>
      <Badge tone={tone}>{note}</Badge>
    </Card>
  );
}
