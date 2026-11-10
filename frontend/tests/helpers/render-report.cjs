const fs = require("node:fs");
const Module = require("node:module");
const { transformSync } = require("next/dist/build/swc");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

// Compile the real TSX components with Next's installed compiler, not copies.
for (const extension of [".ts", ".tsx"]) {
  Module._extensions[extension] = (module, filename) => {
    const { code } = transformSync(fs.readFileSync(filename, "utf8"), {
      filename,
      jsc: {
        parser: { syntax: "typescript", tsx: extension === ".tsx" },
        transform: { react: { runtime: "automatic" } },
      },
      module: { type: "commonjs" },
    });
    module._compile(code, filename);
  };
}
Module._extensions[".css"] = () => {};
const ReportForm =
  require("../../src/components/report/ReportForm.tsx").default;
module.exports = (props) =>
  renderToStaticMarkup(React.createElement(ReportForm, props));
