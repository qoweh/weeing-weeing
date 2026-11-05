// 검증된 본문만 순차 표시한다. LLM 생성 토큰 스트리밍과는 별개의 화면 효과다.
function wait(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted)
      return reject(new DOMException("Aborted", "AbortError"));
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", abort, { once: true });
  });
}

export function createVerifiedReveal({
  append,
  signal,
  reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")
    .matches || false,
  now = () => performance.now(),
  pause = wait,
}) {
  let started = null;
  return async (text) => {
    if (started === null) started = now();
    const characters = Array.from(text);
    for (let offset = 0; offset < characters.length; offset += 12) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      if (reducedMotion || now() - started >= 6000) {
        append(characters.slice(offset).join(""));
        return;
      }
      append(characters.slice(offset, offset + 12).join(""));
      await pause(30, signal);
    }
  };
}
