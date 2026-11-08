import { useEffect, useRef, useState } from "react";
import * as api from "../../api/chat.js";
import { createVerifiedReveal } from "./reveal.js";

export const defaultConditions = {
  asset_id: null,
  model: null,
  date_from: null,
  date_to: null,
  limit: 5,
};

export default function useChatSession(
  open,
  onSessionExpired,
  onQuestionStaged = () => {},
) {
  const [conversation, setConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [moreConversations, setMoreConversations] = useState(false);
  const [topics, setTopics] = useState([]);
  const [questions, setQuestions] = useState([]);
  const [topic, setTopic] = useState(null);
  const [faqLoading, setFaqLoading] = useState(false);
  const [faqError, setFaqError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stream, setStream] = useState(null);
  const [pending, setPending] = useState(null);
  const [rejectedDraft, setRejectedDraft] = useState(null);
  const [chatMode, setChatMode] = useState(false);
  const lock = useRef(false);
  const active = useRef(null);
  const catalog = useRef(null);
  const mounted = useRef(true);

  const guard = (signal) => {
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
  };
  function fail(failure) {
    if (failure.status === 401) onSessionExpired();
    else setError(failure.message);
  }
  // 로그아웃·사용자 변경 시 읽기/상태 갱신을 끊는다. 서버 생성 취소를 의미하지 않는다.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      active.current?.abort();
      catalog.current?.abort();
    };
  }, []);

  async function run(task) {
    if (lock.current) return;
    lock.current = true;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setStream(null);
    setError("");
    try {
      await task(controller.signal);
    } catch (failure) {
      if (!controller.signal.aborted && mounted.current) fail(failure);
    } finally {
      if (mounted.current) {
        lock.current = false;
        setBusy(false);
        setStream(null);
      }
    }
  }
  function receiveStream(requestId, signal) {
    setStream({ requestId, phase: "accepted", text: "" });
    const reveal = createVerifiedReveal({
      signal,
      append: (text) => {
        guard(signal);
        setStream((previous) => ({
          requestId,
          phase: "delivering",
          text: (previous?.text || "") + text,
        }));
      },
    });
    return async (event) => {
      guard(signal);
      const id = event.request_id || event.request?.submission?.request_id;
      if (id !== requestId)
        throw new Error("채팅 스트림의 요청 ID가 다릅니다.");
      if (event.event === "progress")
        setStream((previous) => ({
          ...previous,
          requestId,
          phase: event.phase,
        }));
      if (event.event === "delta") await reveal(event.text);
    };
  }
  async function loadList(signal, append = false) {
    const rows = await api.listChatConversations(
      append ? conversations.length : 0,
      signal,
    );
    guard(signal);
    setConversations((previous) => (append ? [...previous, ...rows] : rows));
    setMoreConversations(rows.length === 50);
  }
  async function loadMessages(id, signal) {
    let after = 0,
      all = [],
      page;
    do {
      page = await api.getChatMessages(id, after, signal);
      guard(signal);
      all = [...all, ...page.messages];
      const next = page.messages.at(-1)?.sequence ?? after;
      if (page.has_more && next <= after)
        throw new Error("대화 기록의 다음 페이지를 확인할 수 없습니다.");
      after = next;
    } while (page.has_more);
    setMessages(all);
    setConversation(page.conversation);
    return { ...page, messages: all };
  }
  async function ensureConversation(signal) {
    if (conversation) return conversation;
    const created = await api.createChatConversation({}, signal);
    guard(signal);
    setConversation(created);
    return created;
  }
  function rememberPending(view) {
    setPending((previous) => ({
      ...view,
      displayQuestion:
        previous?.submission.request_id === view.submission.request_id
          ? previous.displayQuestion
          : undefined,
    }));
  }
  async function finish(view, signal) {
    rememberPending(view);
    const final = await api.waitForChatRequest(view.conversation_id, view, {
      signal,
      onUpdate: (next) => {
        guard(signal);
        rememberPending(next);
      },
    });
    guard(signal);
    if (final.state === "COMPLETED") {
      await loadMessages(final.conversation_id, signal);
      setStream(null);
      setPending(null);
      await loadList(signal);
    }
  }
  async function loadFaq(selected = null) {
    catalog.current?.abort();
    const controller = new AbortController();
    catalog.current = controller;
    setTopic(selected);
    setQuestions([]);
    setFaqError("");
    setFaqLoading(true);
    try {
      const rows = selected
        ? await api.listFaqQuestions(selected.topic_id, controller.signal)
        : await api.listFaqTopics(controller.signal);
      guard(controller.signal);
      if (selected) setQuestions(rows);
      else setTopics(rows);
    } catch (failure) {
      if (!controller.signal.aborted && mounted.current) {
        if (failure.status === 401) onSessionExpired();
        else setFaqError(failure.message);
      }
    } finally {
      if (!controller.signal.aborted && mounted.current) setFaqLoading(false);
    }
  }
  useEffect(() => {
    if (!open) return;
    loadFaq();
    const controller = new AbortController();
    loadList(controller.signal).catch((failure) => {
      if (!controller.signal.aborted) fail(failure);
    });
    return () => {
      controller.abort();
      catalog.current?.abort();
    };
    // 창을 다시 열면 목록을 갱신하고, 현재 대화와 입력 모드는 유지한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function selectConversation(id) {
    if (!id) return;
    return run(async (signal) => {
      const page = await loadMessages(id, signal);
      setChatMode(page.conversation.mode === "CHAT");
      setPending(null);
      const unresolved = [...page.messages]
        .reverse()
        .find((message) => message.role === "user");
      if (unresolved && unresolved.state !== "COMPLETED") {
        const view = await api.getChatRequest(
          id,
          unresolved.request_id,
          signal,
        );
        guard(signal);
        await finish(view, signal);
      }
    });
  }
  return {
    conversation,
    messages,
    conversations,
    moreConversations,
    topics,
    questions,
    topic,
    faqLoading,
    faqError,
    error,
    busy,
    stream,
    pending,
    rejectedDraft,
    chatMode,
    loadFaq,
    reloadMissingFaq: () => {
      if (pending?.error_code === "FAQ_NOT_FOUND") {
        setPending(null);
        loadFaq();
      }
    },
    showFaq: () => {
      setChatMode(false);
      loadFaq();
    },
    moreHistory: () => run((signal) => loadList(signal, true)),
    selectConversation,
    renameConversation: (id, title) =>
      run(async (signal) => {
        const updated = await api.updateChatConversation(id, { title }, signal);
        guard(signal);
        setConversation((current) =>
          current?.conversation_id === id ? updated : current,
        );
        await loadList(signal);
      }),
    deleteConversation: (id) =>
      run(async (signal) => {
        await api.deleteChatConversation(id, signal);
        guard(signal);
        if (conversation?.conversation_id === id) {
          setConversation(null);
          setMessages([]);
          setPending(null);
          setChatMode(false);
          loadFaq();
        }
        await loadList(signal);
      }),
    newConversation: () =>
      run(async (signal) => {
        const created = await api.createChatConversation({}, signal);
        guard(signal);
        setConversation(created);
        setMessages([]);
        setPending(null);
        setChatMode(false);
        await loadList(signal);
        loadFaq();
      }),
    startChat: () =>
      run(async (signal) => {
        const current = await ensureConversation(signal);
        const updated =
          current.mode === "CHAT"
            ? current
            : await api.updateChatConversation(
                current.conversation_id,
                { mode: "CHAT" },
                signal,
              );
        guard(signal);
        setConversation(updated);
        setChatMode(true);
        await loadList(signal);
      }),
    saveConditions: (conditions) =>
      run(async (signal) => {
        if (
          conditions.date_from &&
          conditions.date_to &&
          conditions.date_from > conditions.date_to
        )
          throw new Error("시작일은 종료일보다 늦을 수 없습니다.");
        const current = await ensureConversation(signal);
        const updated = await api.updateChatConversation(
          current.conversation_id,
          { conditions },
          signal,
        );
        guard(signal);
        setConversation(updated);
      }),
    submit: (kind, value, model) =>
      run(async (signal) => {
        if (pending)
          throw new Error(
            "이전 요청의 상태를 먼저 확인하거나 새 대화를 시작하세요.",
          );
        let current = await ensureConversation(signal);
        guard(signal);
        const displayQuestion = kind === "FAQ" ? value.question : value;
        if (current.title === "새 대화" && messages.length === 0) {
          current = await api.updateChatConversation(
            current.conversation_id,
            { title: Array.from(displayQuestion).slice(0, 100).join("") },
            signal,
          );
          guard(signal);
          setConversation(current);
        }
        const submission =
          kind === "FAQ"
            ? { kind, request_id: api.newChatRequestId(), faq_id: value.faq_id }
            : {
                kind,
                request_id: api.newChatRequestId(),
                question: value,
                ...(model ? { model } : {}),
              };
        const initial = {
          conversation_id: current.conversation_id,
          submission,
          displayQuestion,
          state: "SENDING",
          retry_allowed: false,
        };
        setPending(initial);
        if (kind === "CHAT") onQuestionStaged();
        let view;
        try {
          view = await api.submitChatRequest(
            current.conversation_id,
            submission,
            {
              signal,
              ...(kind === "CHAT"
                ? { onEvent: receiveStream(submission.request_id, signal) }
                : {}),
            },
          );
        } catch (failure) {
          guard(signal);
          if (api.isChatRequestRejected(failure)) {
            setPending(null);
            if (kind === "CHAT")
              setRejectedDraft({
                requestId: submission.request_id,
                text: value,
              });
            if (failure.status === 404) {
              setConversation(null);
              setMessages([]);
              setChatMode(false);
            } else if (failure.status === 409) {
              // 다른 창에서 바꾼 모드나 이미 접수된 요청만 조회한다. 새 질문을 자동 전송하지 않는다.
              const page = await loadMessages(current.conversation_id, signal);
              setChatMode(page.conversation.mode === "CHAT");
              const last = [...page.messages]
                .reverse()
                .find((message) => message.role === "user");
              if (last && (api.processing(last) || last.state === "UNKNOWN")) {
                const existing = await api.getChatRequest(
                  current.conversation_id,
                  last.request_id,
                  signal,
                );
                guard(signal);
                rememberPending(existing);
              }
            }
          }
          throw failure;
        }
        guard(signal);
        await finish(view, signal);
      }),
    checkPending: () =>
      run(async (signal) => {
        const view = await api.getChatRequest(
          pending.conversation_id,
          pending.submission.request_id,
          signal,
        );
        guard(signal);
        await finish(view, signal);
      }),
    retryPending: () =>
      run(async (signal) => {
        if (!pending?.retry_allowed) return;
        const view = await api.submitChatRequest(
          pending.conversation_id,
          pending.submission,
          {
            retry: true,
            signal,
            ...(pending.submission.kind === "CHAT"
              ? {
                  onEvent: receiveStream(pending.submission.request_id, signal),
                }
              : {}),
          },
        );
        guard(signal);
        await finish(view, signal);
      }),
  };
}
