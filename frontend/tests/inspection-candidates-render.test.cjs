const { test } = require("node:test");
const assert = require("node:assert/strict");
const render = require("./helpers/render-candidates.cjs");
const cause = {
  cause: "감지면 확인",
  basis: "매뉴얼의 감지면 오염 점검 항목",
  evidence_ids: ["DOC-1"],
  unconfirmed: ["감지면 상태"],
};

test("actual candidate component shows priority and rationale with cited description intact", () => {
  const html = render({
    analysis: {
      suspected_causes: [
        {
          ...cause,
          inspection_priority: "우선 확인",
          priority_reason: "해당 코드의 공식 절차에서 먼저 확인한다.",
          likelihood: "상",
        },
      ],
      evidence: [],
    },
    showSources: false,
  });
  assert.match(html, /우선 확인/);
  assert.match(html, /점검 순서의 근거/);
  assert.match(html, /공식 절차에서 먼저 확인한다/);
  assert.match(html, /매뉴얼의 감지면 오염 점검 항목/);
  assert.match(html, /감지면 상태/);
  assert.doesNotMatch(html, /가능성 상|미평가|출처:/);
});

test("legacy candidate is readable without inventing a priority or dropping its explanation", () => {
  const html = render({
    analysis: { suspected_causes: [{ ...cause, likelihood: "상" }] },
    compact: true,
    showSources: false,
  });
  assert.match(html, /점검 우선순위 미지정/);
  assert.match(html, /후보 설명·확인 사항/);
  assert.match(html, /매뉴얼의 감지면 오염 점검 항목/);
  assert.doesNotMatch(html, /우선 확인|점검 순서의 근거|가능성 상/);
});
