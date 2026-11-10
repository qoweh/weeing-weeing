import EvidenceReferences from "./EvidenceReferences";
import AnalysisText from "./AnalysisText";
import { inspectionPriorityLabel } from "./inspectionPriority";
import { candidateBasis, displayIncidentFacts } from "./incidentFacts";

function CandidateDetail({ cause, analysis, incident, showSources }) {
  return (
    <>
      {cause.inspection_priority && cause.priority_reason && (
        <div className="incident-result__priority-reason">
          <strong>점검 순서의 근거</strong>
          <AnalysisText text={cause.priority_reason} />
        </div>
      )}
      <AnalysisText
        text={displayIncidentFacts(
          candidateBasis(cause.basis, analysis.observed_facts),
          incident,
        )}
      />
      {showSources && (
        <EvidenceReferences
          ids={cause.evidence_ids}
          evidence={analysis.evidence || []}
        />
      )}
      {cause.observations?.length > 0 && (
        <>
          <p>
            <strong>관련 센서 관측</strong>
          </p>
          <ul>
            {cause.observations.map((text, index) => (
              <li key={index}>
                <AnalysisText text={text} />
              </li>
            ))}
          </ul>
        </>
      )}
      {cause.unconfirmed?.length > 0 && (
        <>
          <p>
            <strong>미확인 사항</strong>
          </p>
          <ul>
            {cause.unconfirmed.map((text, index) => (
              <li key={index}>
                <AnalysisText text={text} />
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

export default function CauseCandidates({
  analysis,
  incident,
  compact = false,
  showSources = true,
}) {
  if (!analysis?.suspected_causes?.length) return null;
  return (
    <ul>
      {analysis.suspected_causes.map((cause, index) => (
        <li key={index}>
          <div className="incident-result__candidate-heading">
            <strong>{cause.cause}</strong>
            <span className="incident-result__candidate-status">
              {inspectionPriorityLabel(cause)}
            </span>
          </div>
          {compact ? (
            <details className="incident-result__candidate-detail">
              <summary>
                {showSources
                  ? "후보 설명·출처·확인 사항"
                  : "후보 설명·확인 사항"}
              </summary>
              <CandidateDetail
                cause={cause}
                analysis={analysis}
                incident={incident}
                showSources={showSources}
              />
            </details>
          ) : (
            <CandidateDetail
              cause={cause}
              analysis={analysis}
              incident={incident}
              showSources={showSources}
            />
          )}
        </li>
      ))}
    </ul>
  );
}
