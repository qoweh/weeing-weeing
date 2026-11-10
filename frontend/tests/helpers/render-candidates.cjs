const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const { transformSync } = require("next/dist/build/swc");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const originalJs = Module._extensions[".js"];
const sourceRoot = path.resolve(__dirname, "../../src/incident-hmi");

// Compile the real candidate component and its local helpers without API calls.
function compile(module, filename) {
  const { code } = transformSync(fs.readFileSync(filename, "utf8"), {
    filename,
    jsc: {
      parser: { syntax: "ecmascript", jsx: true },
      transform: { react: { runtime: "automatic" } },
    },
    module: { type: "commonjs" },
  });
  module._compile(code, filename);
}
Module._extensions[".jsx"] = compile;
Module._extensions[".js"] = (module, filename) =>
  filename.startsWith(sourceRoot + path.sep)
    ? compile(module, filename)
    : originalJs(module, filename);
Module._extensions[".css"] = () => {};
Module._extensions[".scss"] = () => {};
const Candidates =
  require("../../src/incident-hmi/components/CauseCandidates.jsx").default;
module.exports = (props) =>
  renderToStaticMarkup(React.createElement(Candidates, props));
