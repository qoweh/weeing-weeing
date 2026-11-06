import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import { setAccessToken } from "../src/api/client.js";
import {
  listFaqTopics,
  listFaqQuestions,
  submitChatRequest,
  waitForChatRequest,
  getChatDocumentFile,
  newChatRequestId,
  isChatRequestRejected,
} from "../src/api/chat.js";

const originalFetch = globalThis.fetch;
const submission = {
  kind: "CHAT",
  request_id: "request-1",
  question: "정비 이력 알려줘",
  conditions: null,
};
const view = (state, extra = {}) => ({
  conversation_id: "conversation-1",
  submission,
  state,
  retry_allowed: false,
  ...extra,
});
const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  globalThis.fetch = originalFetch;
  setAccessToken("");
});

test("FAQ 탐색과 선택은 FAQ 경로·ID만 사용하고 인증을 전달한다", async () => {
  const calls = [];
  setAccessToken("test-session");
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    return json(url.endsWith("topics") ? [] : view("COMPLETED"));
  };
  await listFaqTopics();
  await listFaqQuestions("reports");
  await submitChatRequest("conversation-1", {
    kind: "FAQ",
    request_id: "faq-request",
    faq_id: "FAQ-REPORT-001",
    question: "클라이언트 질문은 보내지 않음",
  });
  assert.equal(
    calls[2][0],
    "/api/chat/conversations/conversation-1/faq-selections",
  );
  assert.deepEqual(JSON.parse(calls[2][1].body), {
    request_id: "faq-request",
    faq_id: "FAQ-REPORT-001",
  });
  assert.equal(calls[2][1].headers.Authorization, "Bearer test-session");
  assert.ok(!calls.some(([url]) => url.endsWith("/messages")));
});
test("조건을 생략한 질문과 같은 ID의 명시적 재시도", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, JSON.parse(options.body)]);
    return json(view("COMPLETED"));
  };
  await submitChatRequest("conversation-1", submission);
  await submitChatRequest("conversation-1", submission, { retry: true });
  assert.ok(!("conditions" in calls[0][1]));
  assert.deepEqual(calls[0][1], calls[1][1]);
  assert.ok(calls[1][0].endsWith("/messages?retry=true"));
});
test("구조화된 503 준비 실패는 재시도 가능 상태를 보존한다", async () => {
  globalThis.fetch = async () =>
    json(
      view("FAILED", { retry_allowed: true, error_code: "PREPARATION_FAILED" }),
      503,
    );
  assert.equal(
    (await submitChatRequest("conversation-1", submission)).retry_allowed,
    true,
  );
});
test("UNKNOWN 결과는 재전송하지 않고 반환한다", async () => {
  let count = 0;
  globalThis.fetch = async () => {
    count++;
    return json(view("UNKNOWN"), 409);
  };
  assert.equal(
    (await submitChatRequest("conversation-1", submission)).state,
    "UNKNOWN",
  );
  assert.equal(count, 1);
});
test("일반 충돌·로그인 만료는 구조화 요청 상태로 오인하지 않는다", async () => {
  globalThis.fetch = async () => json({ detail: "로그인이 필요합니다." }, 401);
  await assert.rejects(
    submitChatRequest("conversation-1", submission),
    (error) => error.status === 401,
  );
});
test("처리 중 상태는 GET으로만 확인하고 저장된 완료 응답을 반환한다", async () => {
  const calls = [],
    updates = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options.method]);
    return json(view(calls.length === 1 ? "RUNNING" : "COMPLETED"));
  };
  const result = await waitForChatRequest("conversation-1", view("RESERVED"), {
    intervalMs: 0,
    onUpdate: (next) => updates.push(next.state),
  });
  assert.equal(result.state, "COMPLETED");
  assert.deepEqual(updates, ["RESERVED", "RUNNING", "COMPLETED"]);
  assert.ok(calls.every(([, method]) => method === "GET"));
});
test("전송 응답을 잃어도 POST를 자동 재실행하지 않는다", async () => {
  let count = 0;
  globalThis.fetch = async () => {
    count++;
    throw new TypeError("offline");
  };
  await assert.rejects(submitChatRequest("conversation-1", submission));
  assert.equal(count, 1);
});
test("로그아웃 취소 신호가 전달되고 폴링을 중단한다", async () => {
  const controller = new AbortController();
  let count = 0;
  globalThis.fetch = async () => {
    count++;
    return json(view("RUNNING"));
  };
  const pending = waitForChatRequest("conversation-1", view("RUNNING"), {
    signal: controller.signal,
    intervalMs: 1000,
  });
  controller.abort();
  await assert.rejects(pending, (error) => error.name === "AbortError");
  assert.equal(count, 0);
});
test("문서 원문은 서버 내부 경로로만 요청한다", async () => {
  let location;
  globalThis.fetch = async (url) => {
    location = url;
    return new Response("%PDF-1.7", {
      headers: { "Content-Type": "application/pdf" },
    });
  };
  const blob = await getChatDocumentFile({
    doc_id: "MANUAL",
    doc_version: "2.0",
    url: "https://untrusted.invalid/secret",
  });
  assert.equal(
    location,
    "/api/documents/original?doc_id=MANUAL&doc_version=2.0",
  );
  assert.equal(await blob.text(), "%PDF-1.7");
});

test("HTTP 시연 환경에서는 getRandomValues로 UUID v4를 만든다", () => {
  const original = globalThis.crypto;
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: { getRandomValues: original.getRandomValues.bind(original) },
  });
  try {
    const id = newChatRequestId();
    assert.match(
      id,
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    assert.notEqual(id, newChatRequestId());
  } finally {
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      value: original,
    });
  }
});

test("확정 접수 거절만 유실·서버 장애·구조화된 요청 상태와 구분한다", () => {
  for (const status of [400, 401, 403, 404, 409, 422])
    assert.equal(
      isChatRequestRejected({ status, data: { detail: "접수 거절" } }),
      true,
    );
  for (const status of [408, 429, 500, 502, 503, 504])
    assert.equal(isChatRequestRejected({ status }), false);
  assert.equal(isChatRequestRejected(new TypeError("응답 유실")), false);
  assert.equal(
    isChatRequestRejected({ status: 409, data: { state: "UNKNOWN" } }),
    false,
  );
  assert.equal(
    isChatRequestRejected({ status: 503, data: { state: "FAILED" } }),
    false,
  );
});
