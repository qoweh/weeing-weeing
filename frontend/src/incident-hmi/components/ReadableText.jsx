import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { formatTimesInText } from "./readableTime";
import "./readable-text.scss";

const components = {
  table: ({ children }) => (
    <div className="readable-text__table">
      <table>{children}</table>
    </div>
  ),
  a: ({ children }) => <span>{children}</span>,
  img: () => null,
};

export default function ReadableText({ text, className = "" }) {
  if (!text) return null;
  return (
    <div className={`readable-text ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={components}
        skipHtml
      >
        {formatTimesInText(text)}
      </ReactMarkdown>
    </div>
  );
}
