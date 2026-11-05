import { createElement as h } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";

// HTML·이미지·외부 링크는 실행하거나 가져오지 않는다. 원문은 기존 서버 출처 버튼으로 연다.
const components = {
  a: ({ children }) => h("span", null, children),
  img: () => null,
  h1: ({ children }) => h("h3", null, children),
  h2: ({ children }) => h("h4", null, children),
  table: ({ children }) =>
    h(
      "div",
      {
        className: "chat-markdown__table",
        role: "region",
        "aria-label": "답변 표",
        tabIndex: 0,
      },
      h("table", null, children),
    ),
};

export default function ChatMarkdown({ children }) {
  return h(
    "div",
    { className: "chat-markdown" },
    h(
      ReactMarkdown,
      { remarkPlugins: [remarkGfm, remarkBreaks], skipHtml: true, components },
      children || "",
    ),
  );
}
