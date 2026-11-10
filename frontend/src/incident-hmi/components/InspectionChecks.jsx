import EvidenceReferences from "./EvidenceReferences";
import AnalysisText from "./AnalysisText";

export default function InspectionChecks({ analysis, showSources = true }) {
  if (!analysis?.recommended_checks?.length) return null;
  return (
    <ol>
      {analysis.recommended_checks.map((text, index) => (
        <li key={index}>
          <AnalysisText text={text} />
          {showSources && (
            <EvidenceReferences
              ids={
                analysis.check_citations?.find(
                  (item) => item.check_index === index,
                )?.evidence_ids || []
              }
              evidence={analysis.evidence || []}
            />
          )}
        </li>
      ))}
    </ol>
  );
}
