import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import {
  registeredIncidentCodes,
  incidentCodeName,
  incidentCodeText,
  incidentCodesText,
  incidentCodeMatches,
  incidentCodeDetail,
} from "../src/components/ui/incidentCodes.ts";

test("all 31 registered backend codes have distinct frontend display names", () => {
  const source = readFileSync(
    new URL("../../src/weeing_weeing/contracts/codes.py", import.meta.url),
    "utf8",
  );
  const official = [...source.matchAll(/"(BTT2-[PMD]\d{2})": "([^"]+)"/g)];
  assert.equal(official.length, 31);
  assert.deepEqual(
    [...registeredIncidentCodes].sort(),
    official.map((m) => m[1]).sort(),
  );
  const labels = registeredIncidentCodes.map((code) => incidentCodeName(code));
  assert.equal(new Set(labels).size, 31);
  for (const [, code, label] of official) {
    assert.ok(incidentCodeMatches([code], label), code);
    assert.ok(incidentCodeText(code).endsWith(`(${code})`));
    assert.doesNotMatch(incidentCodeName(code), /급증|급락/);
  }
});

test("titles preserve the low/high direction and the measured vibration statistic", () => {
  assert.equal(incidentCodeName("BTT2-P03"), "입구 장시간 점유");
  assert.equal(incidentCodeName("BTT2-M02"), "모터 속도 저하");
  assert.equal(incidentCodeName("BTT2-M03"), "모터 속도 상승");
  assert.equal(incidentCodeName("BTT2-M10"), "모터 온도 상승");
  assert.equal(incidentCodeName("BTT2-M14"), "구동측 진동 첨도 상승");
  assert.match(incidentCodeDetail("BTT2-M10"), /외함/);
  assert.match(incidentCodeDetail("BTT2-M12"), /RMS/);
  assert.match(incidentCodeDetail("BTT2-M14"), /첨도/);
});

test("forecast labels describe a possibility rather than a detected fault", () => {
  assert.equal(
    incidentCodeText("BTT2-M02", true),
    "모터 속도 저하 가능성 (BTT2-M02)",
  );
  assert.doesNotMatch(incidentCodeText("BTT2-M02"), /가능성/);
});

test("search accepts original code, new title, legacy name and spacing differences", () => {
  for (const query of ["btt2-p03", "입구", "입구장시간점유", "입구 장기 점유"])
    assert.ok(incidentCodeMatches(["BTT2-P03"], query), query);
  assert.ok(incidentCodeMatches(["BTT2-M02"], "RPM 하한 이탈"));
  assert.equal(incidentCodeMatches(["BTT2-P03"], "모터 온도"), false);
});

test("unknown codes stay visible and cannot use object prototype names as labels", () => {
  for (const code of ["BTT2-X99", "toString", "__proto__"])
    assert.equal(incidentCodeText(code), `미등록 코드 (${code})`);
  assert.equal(incidentCodesText(), "");
  const codes = ["BTT2-P03", "BTT2-M02"];
  const before = [...codes];
  assert.equal(
    incidentCodesText(codes),
    "입구 장시간 점유 (BTT2-P03), 모터 속도 저하 (BTT2-M02)",
  );
  assert.deepEqual(codes, before);
});

const require = createRequire(import.meta.url);
const {
  renderCodes,
  renderLibrary,
  reportDescriptions,
  filterReports,
} = require("./helpers/render-incident-code.cjs");

test("real component renders the readable title followed by a separate small code", () => {
  const html = renderCodes(["BTT2-P03"]);
  assert.match(html, /incident-code-label__name[^>]*>입구 장시간 점유<\/span>/);
  assert.match(
    html,
    /<small class="incident-code-label__code">\(BTT2-P03\)<\/small>/,
  );
  assert.match(renderCodes(["BTT2-M10"], true), /모터 온도 상승 가능성/);
  assert.match(renderCodes(["BTT2-X99"]), /미등록 코드/);
  assert.match(renderCodes(["<script>bad</script>"]), /&lt;script&gt;/);
  assert.doesNotMatch(renderCodes(["<script>bad</script>"]), /<script>/);
  assert.equal(renderCodes([]), "<span>—</span>");
});

test("report names are available without AI and cannot be replaced by AI text", () => {
  const incident = { codes: ["BTT2-M08"] };
  assert.deepEqual(reportDescriptions(incident, null), [
    "DC 버스 전압 상승 (BTT2-M08)",
  ]);
  assert.deepEqual(
    reportDescriptions(incident, {
      observed_facts: "코드: BTT2-M08(임의 원인 확정)",
    }),
    reportDescriptions(incident, null),
  );
});

test("actual report list uses small code markup and searches the original code", () => {
  const row = {
    id: "fake-report",
    name: "fake-report",
    incidentId: "fake-incident",
    issue: incidentCodesText(["BTT2-P03"]),
    issueCodes: ["BTT2-P03"],
  };
  const html = renderLibrary([row]);
  for (const query of ["btt2-p03", "입구장시간점유", "입구 장기 점유"])
    assert.equal(filterReports([row], query).length, 1);
  assert.equal(filterReports([row], "모터 온도").length, 0);
  assert.match(html, /입구 장시간 점유/);
  assert.match(
    html,
    /<small class="incident-code-label__code">\(BTT2-P03\)<\/small>/,
  );
});
