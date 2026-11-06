import ChatMarkdown from "./ChatMarkdown.js";

import { useEffect, useRef, useState } from "react";
import useChatSession, { defaultConditions } from "./useChatSession.js";
import ChatResponse from "./ChatResponse.jsx";
import ChatSourceDialog from "./ChatSourceDialog.jsx";
import Glyph from "../ui/Glyph.tsx";
import "./chat.scss";

export default function ChatWidget({
  screenZoom = 100,
  displayMode = "modal",
  onSessionExpired,
}) {
  const dialog = useRef(null),
    body = useRef(null),
    launcher = useRef(null),
    input = useRef(null),
    historyButton = useRef(null),
    drawerClose = useRef(null),
    filterButton = useRef(null),
    filterClose = useRef(null),
    closeTimer = useRef(null);
  const resize = useRef(null),
    drawerResize = useRef(null),
    drag = useRef(null);
  const [open, setOpen] = useState(false),
    [text, setText] = useState("");
  const [size, setSize] = useState(null),
    [position, setPosition] = useState({ x: 0, y: 0 });
  const [drawerWidth, setDrawerWidth] = useState(null);
  const [source, setSource] = useState(null);
  const [activeDisplay, setActiveDisplay] = useState(displayMode);
  const [closing, setClosing] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [menuId, setMenuId] = useState(null);
  const [menuPosition, setMenuPosition] = useState({ left: 0, top: 0 });
  const chat = useChatSession(open, onSessionExpired, () => setText(""));
  const conditions = chat.conversation?.conditions || defaultConditions;
  const blocked = chat.busy || Boolean(chat.pending);
  const history = chat.conversation
    ? chat.conversations.some(
        (c) => c.conversation_id === chat.conversation.conversation_id,
      )
      ? chat.conversations.map((c) =>
          c.conversation_id === chat.conversation.conversation_id
            ? chat.conversation
            : c,
        )
      : [chat.conversation, ...chat.conversations]
    : chat.conversations;
  const menuConversation = history.find((c) => c.conversation_id === menuId);
  function openHistoryMenu(event, conversationId, fromButton = false) {
    event.preventDefault();
    event.stopPropagation();
    const drawer = event.currentTarget.closest(".chat-history-drawer");
    const rect = drawer.getBoundingClientRect();
    const anchor = event.currentTarget.getBoundingClientRect();
    const zoom = screenZoom / 100;
    const x = fromButton ? anchor.left : event.clientX;
    const y = fromButton ? anchor.bottom : event.clientY;
    setMenuPosition({
      left: Math.max(
        0,
        Math.min((x - rect.left) / zoom, rect.width / zoom - 160),
      ),
      top: Math.max(
        0,
        Math.min((y - rect.top) / zoom, rect.height / zoom - 92),
      ),
    });
    setMenuId(conversationId);
  }
  useEffect(() => {
    if (body.current) body.current.scrollTop = body.current.scrollHeight;
  }, [chat.messages, chat.pending, chat.busy, chat.stream]);
  useEffect(() => {
    if (chat.rejectedDraft) setText(chat.rejectedDraft.text);
  }, [chat.rejectedDraft]);
  useEffect(() => {
    if (chat.chatMode && !chat.busy) input.current?.focus();
  }, [chat.chatMode, chat.busy]);
  useEffect(() => {
    if (historyOpen) drawerClose.current?.focus({ preventScroll: true });
  }, [historyOpen]);
  useEffect(() => {
    if (filterOpen) filterClose.current?.focus({ preventScroll: true });
  }, [filterOpen]);
  useEffect(() => () => clearTimeout(closeTimer.current), []);
  useEffect(() => {
    const fit = () => {
      setPosition({ x: 0, y: 0 });
      setSize(null);
    };
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  function startResize(event) {
    if (activeDisplay === "drawer" || event.button !== 0) return;
    const rect = dialog.current.getBoundingClientRect();
    resize.current = {
      x: event.clientX,
      y: event.clientY,
      width: rect.width / (screenZoom / 100),
      height: rect.height / (screenZoom / 100),
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }
  function moveResize(event) {
    if (!resize.current) return;
    const start = resize.current;
    setSize({
      width: Math.max(
        280,
        start.width + (start.x - event.clientX) / (screenZoom / 100),
      ),
      height: Math.max(
        360,
        start.height + (start.y - event.clientY) / (screenZoom / 100),
      ),
    });
  }
  function keyboardResize(event) {
    const offsets = {
      ArrowLeft: [20, 0],
      ArrowRight: [-20, 0],
      ArrowUp: [0, 20],
      ArrowDown: [0, -20],
    };
    if (!offsets[event.key]) return;
    event.preventDefault();
    const rect = dialog.current.getBoundingClientRect(),
      [width, height] = offsets[event.key];
    setSize({
      width: Math.max(280, rect.width / (screenZoom / 100) + width),
      height: Math.max(360, rect.height / (screenZoom / 100) + height),
    });
  }
  function clampDrawerWidth(width) {
    const max = window.innerWidth / (screenZoom / 100);
    return Math.min(max, Math.max(Math.min(280, max), width));
  }
  function startDrawerResize(event) {
    if (event.button !== 0) return;
    drawerResize.current = {
      x: event.clientX,
      width: dialog.current.getBoundingClientRect().width / (screenZoom / 100),
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
    event.stopPropagation();
    document.body.classList.add("chat-drawer-resizing");
  }
  function endDrawerResize() {
    drawerResize.current = null;
    document.body.classList.remove("chat-drawer-resizing");
  }
  function moveDrawerResize(event) {
    if (!drawerResize.current) return;
    const start = drawerResize.current;
    setDrawerWidth(
      clampDrawerWidth(
        start.width + (start.x - event.clientX) / (screenZoom / 100),
      ),
    );
  }
  function keyboardDrawerResize(event) {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const width =
      dialog.current.getBoundingClientRect().width / (screenZoom / 100);
    setDrawerWidth(
      clampDrawerWidth(width + (event.key === "ArrowLeft" ? 20 : -20)),
    );
  }
  function startDrag(event) {
    if (
      activeDisplay === "drawer" ||
      event.button !== 0 ||
      event.target.closest("button, input, select, summary")
    )
      return;
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      position,
      rect: dialog.current.getBoundingClientRect(),
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }
  function moveDrag(event) {
    if (!drag.current) return;
    const start = drag.current;
    const dx = Math.min(
      window.innerWidth - 8 - start.rect.right,
      Math.max(8 - start.rect.left, event.clientX - start.x),
    );
    const dy = Math.min(
      window.innerHeight - 8 - start.rect.bottom,
      Math.max(8 - start.rect.top, event.clientY - start.y),
    );
    setPosition({
      x: start.position.x + dx / (screenZoom / 100),
      y: start.position.y + dy / (screenZoom / 100),
    });
  }
  function saveConditions(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    closeFilter();
    chat.saveConditions({
      ...conditions,
      ...Object.fromEntries(
        ["asset_id", "model", "date_from", "date_to"].map((key) => [
          key,
          String(form.get(key) || "").trim() || null,
        ]),
      ),
    });
  }
  function send(event) {
    event.preventDefault();
    if (blocked || !text.trim()) return;
    const value = text.trim();
    chat.submit("CHAT", value);
  }
  function closeHistory() {
    setHistoryOpen(false);
    setMenuId(null);
    historyButton.current?.focus();
  }
  function closeFilter() {
    setFilterOpen(false);
    filterButton.current?.focus();
  }
  function close() {
    if (closing) return;
    setHistoryOpen(false);
    setFilterOpen(false);
    setMenuId(null);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      dialog.current.close();
      setOpen(false);
      launcher.current?.focus();
      return;
    }
    setClosing(true);
    closeTimer.current = setTimeout(
      () => {
        dialog.current?.close();
        setOpen(false);
        setClosing(false);
        launcher.current?.focus();
      },
      activeDisplay === "drawer" ? 240 : 180,
    );
  }
  const pending = chat.pending;
  return (
    <div className="chat-widget">
      <button
        ref={launcher}
        className="chat-launcher"
        aria-label="챗봇 열기"
        aria-expanded={open}
        aria-controls="chat-panel"
        onClick={() => {
          clearTimeout(closeTimer.current);
          setClosing(false);
          if (!dialog.current.open) {
            setActiveDisplay(displayMode);
            setPosition({ x: 0, y: 0 });
            setSize(null);
            if (displayMode === "modal") dialog.current.showModal();
            else dialog.current.show();
          }
          setOpen(true);
        }}
      >
        <img src="/assets/ICONS/29bcb.svg" alt="" />
      </button>
      <dialog
        ref={dialog}
        className={`chat-dialog chat-dialog--${activeDisplay}${closing ? " chat-dialog--closing" : ""}`}
        id="chat-panel"
        aria-labelledby="chat-title"
        data-active-drawer={
          filterOpen ? "filter" : historyOpen ? "history" : undefined
        }
        inert={closing}
        style={{
          ...(activeDisplay === "modal" ? size || {} : {}),
          ...(activeDisplay === "drawer" && drawerWidth !== null
            ? { width: drawerWidth }
            : {}),
          ...(activeDisplay === "modal"
            ? { transform: `translate(${position.x}px, ${position.y}px)` }
            : {}),
        }}
        onClose={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            if (menuId) setMenuId(null);
            else if (historyOpen) closeHistory();
            else if (filterOpen) closeFilter();
            else close();
          }
        }}
      >
        {activeDisplay === "drawer" && (
          <button
            type="button"
            className="chat-dialog__drawer-resize"
            aria-label="챗봇 서랍 너비 조절"
            title="드래그하거나 좌우 방향키로 너비 조절"
            onPointerDown={startDrawerResize}
            onPointerMove={moveDrawerResize}
            onPointerUp={endDrawerResize}
            onPointerCancel={endDrawerResize}
            onLostPointerCapture={endDrawerResize}
            onKeyDown={keyboardDrawerResize}
          >
            <span aria-hidden="true" />
          </button>
        )}
        <button
          type="button"
          className="chat-dialog__resize"
          aria-label="챗봇 크기 조절"
          title="드래그하거나 방향키로 크기 조절"
          onPointerDown={startResize}
          onPointerMove={moveResize}
          onLostPointerCapture={() => {
            resize.current = null;
          }}
          onPointerUp={() => {
            resize.current = null;
          }}
          onPointerCancel={() => {
            resize.current = null;
          }}
          onKeyDown={keyboardResize}
        >
          <span aria-hidden="true" />
        </button>
        <header
          className="chat-dialog__header"
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onLostPointerCapture={() => {
            drag.current = null;
          }}
          onPointerUp={() => {
            drag.current = null;
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
        >
          <div className="chat-dialog__identity">
            <span className="chat-dialog__mark" aria-hidden="true">
              <span />
            </span>
            <div>
              <h2 id="chat-title">설비 지원 챗봇</h2>
              <p>
                <img src="/assets/chat/status.svg" alt="" />
                {chat.chatMode ? "자유 대화" : "FAQ 안내"}
              </p>
            </div>
          </div>
          <button
            className="chat-dialog__close"
            aria-label="챗봇 닫기"
            onClick={close}
          >
            <img src="/assets/chat/close.svg" alt="" />
          </button>
        </header>
        <div className="chat-controls">
          <button
            ref={historyButton}
            type="button"
            className="chat-history-trigger"
            aria-expanded={historyOpen}
            aria-controls="chat-history-drawer"
            onClick={() => {
              setFilterOpen(false);
              setHistoryOpen(true);
            }}
          >
            <span aria-hidden="true">☰</span> 내 대화
          </button>
          <span className="chat-controls__title">
            {chat.conversation?.title || "새 대화"}
          </span>
          <button
            ref={filterButton}
            type="button"
            className="chat-filter-trigger"
            aria-expanded={filterOpen}
            aria-controls="chat-filter-drawer"
            onClick={() => {
              setHistoryOpen(false);
              setFilterOpen(true);
            }}
          >
            검색 조건
          </button>
        </div>
        <div
          className={`chat-history-overlay${historyOpen ? " is-open" : ""}`}
          aria-hidden={!historyOpen}
          inert={!historyOpen}
          onKeyDown={(event) => {
            if (event.key !== "Tab") return;
            const buttons = [
              ...event.currentTarget.querySelectorAll(
                ".chat-history-drawer button:not(:disabled)",
              ),
            ];
            const first = buttons[0],
              last = buttons[buttons.length - 1];
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first?.focus();
            }
          }}
        >
          <button
            type="button"
            className="chat-history-overlay__backdrop"
            aria-label="대화 목록 닫기"
            tabIndex={-1}
            onClick={closeHistory}
          />
          <section
            id="chat-history-drawer"
            className="chat-history-drawer"
            aria-label="내 대화"
            onClick={(event) => {
              if (!event.target.closest(".chat-history-entry__menu"))
                setMenuId(null);
            }}
          >
            <div className="chat-history-drawer__header">
              <h3>내 대화</h3>
              <button
                ref={drawerClose}
                type="button"
                aria-label="대화 목록 닫기"
                onClick={closeHistory}
              >
                ×
              </button>
            </div>
            <button
              type="button"
              className="chat-history-drawer__new"
              disabled={chat.busy}
              onClick={() => {
                setText("");
                chat.newConversation();
                closeHistory();
              }}
            >
              <span aria-hidden="true">＋</span> 새 대화
            </button>
            <div
              className="chat-history-drawer__list"
              onScroll={() => setMenuId(null)}
            >
              <p className="chat-history-drawer__label">대화 기록</p>
              {history.length ? (
                history.map((c) => (
                  <div
                    key={c.conversation_id}
                    className="chat-history-entry"
                    onContextMenu={(event) =>
                      openHistoryMenu(event, c.conversation_id)
                    }
                  >
                    <button
                      type="button"
                      className={`chat-history-drawer__item${c.conversation_id === chat.conversation?.conversation_id ? " is-active" : ""}`}
                      aria-current={
                        c.conversation_id === chat.conversation?.conversation_id
                          ? "true"
                          : undefined
                      }
                      disabled={chat.busy}
                      onClick={() => {
                        chat.selectConversation(c.conversation_id);
                        closeHistory();
                      }}
                    >
                      <span>{c.title || "새 대화"}</span>
                      <small>
                        {new Date(c.updated_at).toLocaleDateString("ko-KR")}
                      </small>
                    </button>
                    <button
                      type="button"
                      className="chat-history-entry__menu-button"
                      aria-label={`${c.title || "새 대화"} 메뉴`}
                      aria-expanded={menuId === c.conversation_id}
                      onClick={(event) => {
                        if (menuId === c.conversation_id) setMenuId(null);
                        else openHistoryMenu(event, c.conversation_id, true);
                      }}
                    >
                      ⋯
                    </button>
                  </div>
                ))
              ) : (
                <p className="chat-history-drawer__empty">
                  아직 저장된 대화가 없습니다.
                </p>
              )}
              {chat.moreConversations && (
                <button
                  type="button"
                  className="chat-history-drawer__more"
                  onClick={chat.moreHistory}
                  disabled={chat.busy}
                >
                  목록 더 보기
                </button>
              )}
            </div>
            {menuConversation && (
              <div className="chat-history-entry__menu" style={menuPosition}>
                <button
                  type="button"
                  disabled={chat.busy}
                  onClick={() => {
                    const title = window.prompt(
                      "대화 이름을 입력하세요",
                      menuConversation.title || "",
                    );
                    setMenuId(null);
                    if (title?.trim())
                      chat.renameConversation(
                        menuConversation.conversation_id,
                        title.trim().slice(0, 100),
                      );
                  }}
                >
                  이름 변경
                </button>
                <button
                  type="button"
                  disabled={chat.busy}
                  onClick={() => {
                    setMenuId(null);
                    if (
                      window.confirm(
                        "이 대화를 삭제할까요? 대화 내용도 함께 삭제됩니다.",
                      )
                    )
                      chat.deleteConversation(menuConversation.conversation_id);
                  }}
                >
                  삭제
                </button>
              </div>
            )}
          </section>
        </div>
        <div
          className={`chat-history-overlay chat-filter-overlay${filterOpen ? " is-open" : ""}`}
          aria-hidden={!filterOpen}
          inert={!filterOpen}
        >
          <button
            type="button"
            className="chat-history-overlay__backdrop"
            aria-label="검색 조건 닫기"
            tabIndex={-1}
            onClick={closeFilter}
          />
          <section
            id="chat-filter-drawer"
            className="chat-history-drawer chat-filter-drawer chat-conditions"
            aria-label="검색 조건"
          >
            <div className="chat-history-drawer__header">
              <h3>검색 조건</h3>
              <button
                ref={filterClose}
                type="button"
                aria-label="검색 조건 닫기"
                onClick={closeFilter}
              >
                ×
              </button>
            </div>
            <form
              key={`${chat.conversation?.conversation_id}:${JSON.stringify(conditions)}`}
              onSubmit={saveConditions}
            >
              <label>
                설비 ID
                <input
                  name="asset_id"
                  maxLength={100}
                  defaultValue={conditions.asset_id || ""}
                  placeholder="전체 설비"
                  disabled={blocked}
                />
              </label>
              <label>
                설비 모델
                <input
                  name="model"
                  maxLength={100}
                  defaultValue={conditions.model || ""}
                  placeholder="지정 안 함"
                  disabled={blocked}
                />
              </label>
              <label>
                조치 시작일
                <input
                  name="date_from"
                  type="date"
                  defaultValue={conditions.date_from || ""}
                  disabled={blocked}
                />
              </label>
              <label>
                조치 종료일
                <input
                  name="date_to"
                  type="date"
                  defaultValue={conditions.date_to || ""}
                  disabled={blocked}
                />
              </label>
              <p>
                기간은 정비 조치일 기준입니다. 모델 조건은 매뉴얼 검색에
                사용합니다.
              </p>
              <button disabled={blocked}>조건 적용</button>
            </form>
          </section>
        </div>
        <div ref={body} className="chat-dialog__body">
          {!chat.messages.length && (
            <div className="chat-dialog__message">
              <strong>안녕하세요!</strong>
              <p>
                FAQ 주제와 질문을 선택하거나, 채팅 시작을 눌러 매뉴얼·정비이력을
                물어보세요.
              </p>
            </div>
          )}
          <div
            className="chat-dialog__conversation"
            role="log"
            aria-label="대화 내용"
            aria-live="polite"
            aria-relevant="additions"
          >
            {chat.messages.map((message) => (
              <div
                key={message.sequence}
                className={`chat-dialog__message-row chat-dialog__message-row--${message.role}`}
              >
                {message.role === "assistant" && (
                  <span
                    className="chat-dialog__message-icon"
                    aria-hidden="true"
                  >
                    ✦
                  </span>
                )}
                <div className="chat-dialog__message">
                  {message.response ? (
                    <ChatResponse
                      response={message.response}
                      onSource={setSource}
                    />
                  ) : (
                    message.content
                  )}
                </div>
              </div>
            ))}
            {pending &&
              !chat.messages.some(
                (message) =>
                  message.request_id === pending.submission.request_id,
              ) && (
                <div className="chat-dialog__message-row chat-dialog__message-row--user">
                  <div className="chat-dialog__message">
                    {pending.displayQuestion ||
                      pending.submission.question ||
                      chat.questions.find(
                        (q) => q.faq_id === pending.submission.faq_id,
                      )?.question ||
                      "FAQ 질문 선택"}
                  </div>
                </div>
              )}
            {chat.busy && (
              <p role="status">
                {{
                  accepted: "요청을 확인하고 있습니다…",
                  searching: "자료 검색 중…",
                  generating: "답변 작성 중…",
                  verifying: "근거 검토 중…",
                  saving: "답변을 저장하고 있습니다…",
                  delivering: "검증된 답변을 표시하고 있습니다…",
                }[chat.stream?.phase] ||
                  "답변과 대화 상태를 확인하고 있습니다…"}
              </p>
            )}
            {chat.busy &&
              chat.stream?.text &&
              !chat.messages.some(
                (message) =>
                  message.role === "assistant" &&
                  message.request_id === chat.stream.requestId,
              ) && (
                <div
                  className="chat-dialog__message-row chat-dialog__message-row--assistant"
                  aria-live="off"
                >
                  <span
                    className="chat-dialog__message-icon"
                    aria-hidden="true"
                  >
                    ✦
                  </span>
                  <div className="chat-dialog__message">
                    <ChatMarkdown>{chat.stream.text}</ChatMarkdown>
                  </div>
                </div>
              )}
            {pending && !chat.busy && (
              <div className="chat-pending" role="status">
                {pending.response ? (
                  <ChatResponse
                    response={pending.response}
                    onSource={setSource}
                  />
                ) : (
                  <p>
                    {pending.state === "UNKNOWN"
                      ? "처리 결과와 과금 여부를 확인할 수 없어 자동 재전송하지 않습니다."
                      : pending.state === "FAILED"
                        ? pending.error_code === "FAQ_NOT_FOUND"
                          ? "선택한 FAQ를 더 이상 조회할 수 없습니다. 목록을 새로 받아 주세요."
                          : "요청 실행을 준비하지 못했습니다."
                        : "요청이 서버에서 계속 처리 중일 수 있습니다. 상태를 확인해 주세요."}
                  </p>
                )}
                <button type="button" onClick={chat.checkPending}>
                  상태 확인
                </button>
                {pending.retry_allowed && (
                  <button type="button" onClick={chat.retryPending}>
                    같은 요청 다시 시도
                  </button>
                )}
                {pending.error_code === "FAQ_NOT_FOUND" && (
                  <button type="button" onClick={chat.reloadMissingFaq}>
                    FAQ 목록 새로고침
                  </button>
                )}
              </div>
            )}
          </div>
          {chat.error && (
            <p role="alert" className="chat-error">
              {chat.error}
            </p>
          )}
          {!chat.chatMode && (
            <section className="chat-dialog__examples" aria-label="FAQ 목록">
              <h3>{chat.topic?.title || "이런 내용을 물어볼 수 있어요"}</h3>
              {chat.topic && (
                <button type="button" onClick={() => chat.loadFaq()}>
                  주제 목록으로
                </button>
              )}
              {chat.faqLoading ? (
                <p role="status">FAQ를 불러오는 중입니다.</p>
              ) : chat.faqError ? (
                <p role="alert">
                  {chat.faqError}{" "}
                  <button onClick={() => chat.loadFaq(chat.topic)}>
                    다시 불러오기
                  </button>
                </p>
              ) : chat.topic ? (
                chat.questions.length ? (
                  chat.questions.map((q) => (
                    <button
                      key={q.faq_id}
                      type="button"
                      disabled={blocked}
                      onClick={() => chat.submit("FAQ", q)}
                    >
                      {q.question}
                    </button>
                  ))
                ) : (
                  <p>등록된 질문이 없습니다. 채팅 시작을 이용해 주세요.</p>
                )
              ) : chat.topics.length ? (
                chat.topics.map((t) => (
                  <button
                    key={t.topic_id}
                    type="button"
                    onClick={() => chat.loadFaq(t)}
                  >
                    {t.title}
                  </button>
                ))
              ) : (
                <p>등록된 FAQ 주제가 없습니다. 채팅 시작을 이용해 주세요.</p>
              )}
            </section>
          )}
        </div>
        <footer className="chat-dialog__footer">
          <div className="chat-mode-buttons">
            <button type="button" onClick={chat.showFaq}>
              FAQ 목록
            </button>
            <button
              type="button"
              disabled={blocked}
              aria-pressed={chat.chatMode}
              onClick={chat.startChat}
            >
              채팅 시작
            </button>
          </div>
          {chat.chatMode && (
            <form className="chat-dialog__composer" onSubmit={send}>
              <textarea
                ref={input}
                aria-label="챗봇 질문"
                value={text}
                onChange={(event) => setText(event.target.value)}
                maxLength={2000}
                rows={2}
                placeholder="매뉴얼이나 정비이력을 물어보세요"
                disabled={blocked}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    event.currentTarget.form.requestSubmit();
                  }
                }}
              />
              <button disabled={blocked || !text.trim()} aria-label="질문 전송">
                {blocked || !text.trim() ? (
                  <img src="/assets/chat/send-disabled.svg" alt="" />
                ) : (
                  <Glyph name="arrow-right" size={18} />
                )}
              </button>
            </form>
          )}
          <p>대화 기록은 본인만 조회할 수 있습니다.</p>
        </footer>
      </dialog>
      {source && (
        <ChatSourceDialog
          source={source}
          onClose={() => setSource(null)}
          onSessionExpired={onSessionExpired}
        />
      )}
    </div>
  );
}
