const fs = require("node:fs");
const Module = require("node:module");
const { transformSync } = require("next/dist/build/swc");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

// Render the real components with Next's compiler, without requests or credentials.
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
Module._extensions[".scss"] = () => {};
const IncidentCodes =
  require("../../src/components/ui/IncidentCodeLabel.tsx").default;
const {
  LibraryTable,
  filterRows,
} = require("../../src/components/ui/library.tsx");
const {
  alarmDescriptions,
} = require("../../src/components/report/reportPresentation.ts");
module.exports = {
  renderCodes: (codes, prediction = false) =>
    renderToStaticMarkup(
      React.createElement(IncidentCodes, { codes, prediction }),
    ),
  renderLibrary: (rows) =>
    renderToStaticMarkup(
      React.createElement(LibraryTable, {
        rows,
        report: true,
        title: "사건",
        onOpen: () => {},
      }),
    ),
  reportDescriptions: alarmDescriptions,
  filterReports: (rows, query) =>
    filterRows(rows, query, { period: "", docType: "" }),
};
