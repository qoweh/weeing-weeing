import ReadableText from "./ReadableText";
import { humanizeAnalysisText } from "./analysisWording";

export default function AnalysisText({ text, className }) {
  return (
    <ReadableText text={humanizeAnalysisText(text)} className={className} />
  );
}
