import test from "node:test";
import assert from "node:assert/strict";
import { createVerifiedReveal } from "../src/components/chat/reveal.js";

test("검증된 조각을 순차 표시하고 줄바꿈과 유니코드를 보존한다", async () => {
  const chunks = [],
    waits = [];
  let clock = 0;
  const reveal = createVerifiedReveal({
    append: (text) => chunks.push(text),
    now: () => clock,
    pause: async (ms) => {
      waits.push(ms);
      clock += ms;
    },
  });
  const text = "## 확인\n\n온도 🌡️ 센서의 측정값과 판정 기준을 설명합니다.";
  await reveal(text);
  assert.ok(chunks.length > 1);
  assert.equal(chunks.join(""), text);
  assert.ok(waits.length > 0);
});

test("모션 줄이기 설정에서는 즉시 표시한다", async () => {
  const chunks = [];
  const reveal = createVerifiedReveal({
    append: (text) => chunks.push(text),
    reducedMotion: true,
    pause: async () => {
      throw new Error("must not delay");
    },
  });
  await reveal("검증된 답변입니다.");
  assert.deepEqual(chunks, ["검증된 답변입니다."]);
});

test("여러 전송 조각을 합쳐 6초 이후에는 지연을 추가하지 않는다", async () => {
  const chunks = [];
  let clock = 0;
  const reveal = createVerifiedReveal({
    append: (text) => chunks.push(text),
    now: () => clock,
    pause: async () => {
      clock += 6000;
    },
  });
  await reveal("123456789012추가 본문");
  const count = chunks.length;
  await reveal("다음 전송 조각");
  assert.equal(chunks.length, count + 1);
  assert.equal(chunks.at(-1), "다음 전송 조각");
});

test("취소 후에는 표시를 이어가지 않는다", async () => {
  const signal = new AbortController();
  let chunks = 0;
  const reveal = createVerifiedReveal({
    signal: signal.signal,
    append: () => {
      chunks++;
    },
    pause: async () => signal.abort(),
  });
  await assert.rejects(reveal("123456789012중단 이후 본문"), {
    name: "AbortError",
  });
  assert.equal(chunks, 1);
});
