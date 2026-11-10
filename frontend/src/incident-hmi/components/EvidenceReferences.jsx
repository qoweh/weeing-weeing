import { referenceLabels } from "./evidenceLabels";
import "./EvidenceReferences.css";

export default function EvidenceReferences({ ids = [], evidence = [] }) {
  if (!ids.length) return null;
  return (
    <small className="evidence-references">
      출처: {referenceLabels(ids, evidence).join(" / ")}
    </small>
  );
}

export function EvidenceTrace({ evidence }) {
  return (
    <details className="evidence-trace">
      <summary>근거 식별 정보</summary>
      <code>{evidence.evidence_id}</code>
    </details>
  );
}
