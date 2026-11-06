import { incidentCodeDetail, incidentCodeName } from "./incidentCodes";
import "./IncidentCodeLabel.css";

export function IncidentCodeLabel({
  code,
  prediction = false,
}: {
  code: string;
  prediction?: boolean;
}) {
  return (
    <span
      className="incident-code-label"
      data-code={code}
      title={incidentCodeDetail(code)}
    >
      <span className="incident-code-label__name">
        {incidentCodeName(code, prediction)}
      </span>{" "}
      <small className="incident-code-label__code">({code})</small>
    </span>
  );
}

export default function IncidentCodes({
  codes,
  prediction = false,
  emptyLabel = "—",
}: {
  codes?: readonly string[] | null;
  prediction?: boolean;
  emptyLabel?: string;
}) {
  if (!codes?.length) return <span>{emptyLabel}</span>;
  return (
    <span className="incident-codes">
      {codes.map((code, index) => (
        <IncidentCodeLabel
          key={`${code}:${index}`}
          code={code}
          prediction={prediction}
        />
      ))}
    </span>
  );
}
