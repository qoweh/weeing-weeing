import { test } from "node:test";
import assert from "node:assert/strict";
import { listReports, setAccessToken, saveReport } from "../src/api/client.js";

test("계정 전환과 저장 후에는 진행 중인 이전 목록 요청을 재사용하지 않는다", async () => {
  const original = globalThis.fetch;
  const pending = [];
  globalThis.fetch = (url, options) => {
    if (options.method === "POST")
      return Promise.resolve(new Response("{}", { status: 200 }));
    return new Promise((resolve) => pending.push({ resolve, auth: options.headers.Authorization }));
  };
  const finish = (index, id) =>
    pending[index].resolve(new Response(JSON.stringify([{ report_id: id }])));
  try {
    setAccessToken("account-a");
    const first = listReports();
    setAccessToken("account-b");
    const second = listReports();
    assert.equal(pending.length, 2);
    assert.equal(pending[1].auth, "Bearer account-b");
    finish(0, "a");
    await first;
    const shared = listReports();
    assert.equal(pending.length, 2);
    await saveReport(undefined, {});
    const fresh = listReports();
    assert.equal(pending.length, 3);
    finish(1, "b-before");
    finish(2, "b-after");
    assert.equal((await second)[0].report_id, "b-before");
    assert.equal((await shared)[0].report_id, "b-before");
    assert.equal((await fresh)[0].report_id, "b-after");
  } finally {
    setAccessToken("");
    globalThis.fetch = original;
  }
});
