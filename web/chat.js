import {
  COMPOSER_MAX_LINES,
  NEW_CONVERSATION,
  REQUEST_TIMEOUT_MS,
  STILL_THINKING_MESSAGE,
  STILL_THINKING_MS,
  TIMEOUT_MESSAGE,
  WAITING_MESSAGE,
  WARMING_UP_MESSAGE,
  compactNotice,
  counterText,
  fillText,
  interpretChat,
  isNearBottom,
  isRetryable,
  normalizeStarters,
  outcomeStyle,
  relativeTime,
  remainingHint,
  revealScrollTop,
  safeHttpUrl,
  shouldWarmRetry,
  validateDraft,
} from "./logic.js";

const root = document.body;
const labelEl = document.querySelector("#ai-label");
const noticeEl = document.querySelector("#logging-notice");
const noticeSummary = document.querySelector("#logging-notice-summary");
const noticeDetail = document.querySelector("#logging-notice-detail");
const messagesEl = document.querySelector("#messages");
const form = document.querySelector("#composer");
const box = document.querySelector("#message");
const send = document.querySelector("#send");
const statusEl = document.querySelector("#status");
const countEl = document.querySelector("#char-count");
const newChat = document.querySelector("#new-chat");
const sessionEl = document.querySelector("#session-id");
const copyBtn = document.querySelector("#copy-id");
const contactRow = document.querySelector("#contact-row");
const contactLink = document.querySelector("#contact-link");
const about = document.querySelector("#about");

const apiBase = (root.dataset.apiBase || document.documentElement.dataset.apiBase || "").replace(/\/$/, "");

let maxChars = 1000;
let opening = "";
let botName = "Bot";
let starters = [];
let waiting = false;
let sessionId = "";
let waitTimer = 0;
let activeAbort = null;
let lineHeight = 0;

function api(path) {
  return `${apiBase}${path}`;
}

function timeoutMs() {
  const raw = Number(root.dataset.requestTimeoutMs);
  return Number.isFinite(raw) && raw > 0 ? raw : REQUEST_TIMEOUT_MS;
}

function stillThinkingMs() {
  const raw = Number(root.dataset.stillThinkingMs);
  return Number.isFinite(raw) && raw > 0 ? raw : STILL_THINKING_MS;
}

function setStatus(text) {
  fillText(statusEl, text);
}

function showSession(id) {
  fillText(sessionEl, id || "none yet");
  copyBtn.disabled = !id;
}

function setBusy(on) {
  waiting = on;
  send.disabled = on;
  send.setAttribute("aria-busy", on ? "true" : "false");
  send.classList.toggle("busy", on);
}

function readerAtEnd() {
  return isNearBottom(messagesEl.scrollTop, messagesEl.clientHeight, messagesEl.scrollHeight);
}

function append(item, follow) {
  messagesEl.append(item);
  if (!follow) return;
  messagesEl.scrollTop = revealScrollTop(
    item.offsetTop,
    item.offsetHeight,
    messagesEl.clientHeight,
    messagesEl.scrollHeight,
  );
}

function fillLoggingNotice(full, short) {
  const parts = compactNotice(full, short);
  fillText(noticeSummary, parts.summary);
  if (parts.detail) {
    fillText(noticeDetail, parts.detail);
    noticeDetail.hidden = false;
    noticeEl.classList.remove("notice-static");
    noticeEl.open = false;
  } else {
    fillText(noticeDetail, "");
    noticeDetail.hidden = true;
    noticeEl.classList.add("notice-static");
    noticeEl.open = false;
  }
}

function addNote(text) {
  const note = document.createElement("p");
  note.className = "session-note";
  fillText(note, text);
  append(note, readerAtEnd());
}

function addMessage(role, text, restart) {
  const follow = readerAtEnd();
  const item = document.createElement("div");
  item.className = role === "visitor" ? "msg visitor" : "msg bot";
  const at = Date.now();
  item.dataset.sentAt = String(at);
  if (role !== "visitor") {
    const meta = document.createElement("p");
    meta.className = "msg-meta";
    fillText(meta, botName);
    item.append(meta);
  }
  const paragraph = document.createElement("p");
  fillText(paragraph, text);
  item.append(paragraph);
  item.title = relativeTime(at);
  item.addEventListener("mouseenter", () => {
    item.title = relativeTime(Number(item.dataset.sentAt));
  });
  item.addEventListener("focusin", () => {
    item.title = relativeTime(Number(item.dataset.sentAt));
  });
  if (restart) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "restart";
    fillText(button, "Start a new chat");
    button.addEventListener("click", () => resetChat());
    item.append(button);
  }
  append(item, follow);
}

function addSystemNotice(text, { retryText = "", restart = false } = {}) {
  const follow = readerAtEnd();
  const item = document.createElement("div");
  item.className = "system-notice";
  const paragraph = document.createElement("p");
  fillText(paragraph, text);
  item.append(paragraph);
  if (retryText) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "retry";
    fillText(button, "Retry");
    button.addEventListener("click", () => {
      if (waiting) return;
      item.remove();
      void sendMessage(retryText);
    });
    item.append(button);
  }
  if (restart) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "restart";
    fillText(button, "Start a new chat");
    button.addEventListener("click", () => resetChat());
    item.append(button);
  }
  append(item, follow);
}

function hideStarters() {
  const list = messagesEl.querySelector(".starters");
  if (list) list.remove();
}

function showStarters() {
  hideStarters();
  if (!starters.length) return;
  const list = document.createElement("ul");
  list.className = "starters";
  list.setAttribute("aria-label", "Suggested questions");
  for (const question of starters) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    fillText(button, question);
    button.addEventListener("click", () => {
      if (waiting) return;
      hideStarters();
      void sendMessage(question);
    });
    item.append(button);
    list.append(item);
  }
  append(list, true);
}

function stopWaitTimers() {
  if (waitTimer) {
    clearTimeout(waitTimer);
    waitTimer = 0;
  }
}

function setTyping(on) {
  stopWaitTimers();
  const current = messagesEl.querySelector(".typing");
  if (current) current.remove();
  if (!on) {
    setStatus("");
    return;
  }
  const follow = readerAtEnd();
  const item = document.createElement("div");
  item.className = "msg bot typing";
  item.setAttribute("aria-hidden", "true");
  const dots = document.createElement("span");
  dots.className = "typing-dots";
  for (let i = 0; i < 3; i++) {
    dots.append(document.createElement("span"));
  }
  item.append(dots);
  append(item, follow);
  setStatus(WAITING_MESSAGE);
  waitTimer = window.setTimeout(() => {
    waitTimer = 0;
    if (!messagesEl.querySelector(".typing")) return;
    setStatus(STILL_THINKING_MESSAGE);
  }, stillThinkingMs());
}

function clearMessages() {
  for (const node of [...messagesEl.children]) {
    if (node === noticeEl) continue;
    node.remove();
  }
}

function resetChat() {
  if (activeAbort) {
    activeAbort.abort();
    activeAbort = null;
  }
  stopWaitTimers();
  setTyping(false);
  setBusy(false);
  sessionId = "";
  showSession("");
  clearMessages();
  if (opening) addMessage("bot", opening, false);
  showStarters();
  box.value = "";
  resizeComposer();
  updateCounter();
  setStatus("");
  box.focus();
}

function measureLineHeight() {
  const styles = window.getComputedStyle(box);
  const parsed = Number.parseFloat(styles.lineHeight);
  if (Number.isFinite(parsed) && parsed > 0) {
    lineHeight = parsed;
    return;
  }
  const size = Number.parseFloat(styles.fontSize);
  lineHeight = Number.isFinite(size) ? size * 1.45 : 24;
}

function resizeComposer() {
  if (!lineHeight) measureLineHeight();
  const maxHeight = lineHeight * COMPOSER_MAX_LINES + 24;
  box.style.height = "auto";
  const next = Math.min(box.scrollHeight, maxHeight);
  box.style.height = `${Math.max(44, next)}px`;
  box.style.overflowY = box.scrollHeight > maxHeight ? "auto" : "hidden";
}

function updateCounter() {
  fillText(countEl, counterText(box.value.length, maxChars));
}

async function loadConfig() {
  const response = await fetch(api("/api/config"));
  if (!response.ok) throw new Error("config");
  const config = await response.json();
  maxChars = Number(config.max_message_chars) || 1000;
  opening = String(config.opening_message || "");
  botName = String(config.bot_name || "Bot").trim() || "Bot";
  starters = normalizeStarters(config.starter_questions);
  const label = String(config.ai_label || "This is an AI.");
  fillText(labelEl, label);
  document.title = label;
  fillLoggingNotice(
    String(config.logging_notice || ""),
    String(config.logging_notice_short || ""),
  );
  box.placeholder = String(config.composer_placeholder || "Ask a question…");
  const contact = safeHttpUrl(config.contact_url);
  if (contact) {
    contactLink.href = contact;
    contactRow.hidden = false;
  } else {
    contactRow.hidden = true;
  }
  clearMessages();
  if (opening) addMessage("bot", opening, false);
  showStarters();
  resizeComposer();
  updateCounter();
}

async function postChat(text, sentId) {
  const payload = { message: text };
  if (sentId) payload.session_id = sentId;
  const controller = new AbortController();
  activeAbort = controller;
  const timer = window.setTimeout(() => controller.abort(), timeoutMs());
  try {
    const response = await fetch(api("/api/chat"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    return { httpStatus: response.status, body: await response.json(), timedOut: false };
  } catch (error) {
    if (error && error.name === "AbortError") {
      return { httpStatus: 0, body: null, timedOut: true };
    }
    return { httpStatus: 0, body: null, timedOut: false };
  } finally {
    clearTimeout(timer);
    if (activeAbort === controller) activeAbort = null;
  }
}

function rememberSession(outcome) {
  if (!outcome.sessionId) return;
  sessionId = outcome.sessionId;
  showSession(sessionId);
}

function showOutcome(outcome, text, visitorShown) {
  if (outcome.replaced) addNote(NEW_CONVERSATION);
  if (!visitorShown) addMessage("visitor", text, false);
  if (outcomeStyle(outcome.kind) === "reply") {
    addMessage("bot", outcome.reply, false);
  } else if (outcome.restart) {
    addSystemNotice(outcome.reply, { restart: true });
  } else if (isRetryable(outcome.kind)) {
    addSystemNotice(outcome.reply, { retryText: text });
  } else {
    addSystemNotice(outcome.reply);
  }
  rememberSession(outcome);
  const hint = remainingHint(outcome.session);
  if (hint) setStatus(hint);
}

async function sendMessage(text) {
  hideStarters();
  let sentId = sessionId;
  setBusy(true);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  setTyping(true);
  let result = await postChat(text, sentId);
  let outcome = result.timedOut
    ? {
        kind: "timeout",
        reply: TIMEOUT_MESSAGE,
        sessionId: sentId,
        session: null,
        replaced: false,
        keepDraft: false,
        restart: false,
      }
    : interpretChat(sentId, result.httpStatus, result.body);
  let visitorShown = false;
  if (!result.timedOut && shouldWarmRetry(outcome)) {
    setTyping(false);
    if (outcome.replaced) addNote(NEW_CONVERSATION);
    addMessage("visitor", text, false);
    visitorShown = true;
    addMessage("bot", WARMING_UP_MESSAGE, false);
    rememberSession(outcome);
    sentId = outcome.sessionId || sentId;
    setTyping(true);
    result = await postChat(text, sentId);
    outcome = result.timedOut
      ? {
          kind: "timeout",
          reply: TIMEOUT_MESSAGE,
          sessionId: sentId,
          session: null,
          replaced: false,
          keepDraft: false,
          restart: false,
        }
      : interpretChat(sentId, result.httpStatus, result.body);
  }
  setTyping(false);
  showOutcome(outcome, text, visitorShown);
  box.value = "";
  resizeComposer();
  updateCounter();
  setBusy(false);
  box.focus();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (waiting) return;
  const draft = validateDraft(box.value, maxChars);
  if (!draft.ok) {
    setStatus(draft.message);
    return;
  }
  void sendMessage(draft.cleaned);
});

box.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

box.addEventListener("input", () => {
  resizeComposer();
  updateCounter();
});

newChat.addEventListener("click", () => {
  about.open = false;
  resetChat();
});

document.addEventListener("click", (event) => {
  if (about.open && !about.contains(event.target)) about.open = false;
});

about.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || !about.open) return;
  about.open = false;
  about.querySelector("summary").focus();
});

copyBtn.addEventListener("click", async () => {
  if (!sessionId) return;
  try {
    await navigator.clipboard.writeText(sessionId);
    setStatus("Copied the session id.");
  } catch {
    setStatus("Copy failed. Select the session id and copy it yourself.");
  }
});

if (new URLSearchParams(window.location.search).get("widget") === "1") {
  root.classList.add("widget-frame");
  labelEl.hidden = true;
}

showSession("");
measureLineHeight();
resizeComposer();
loadConfig().catch(() => {
  fillText(labelEl, "This is an AI.");
  setStatus("The chat settings could not be loaded.");
});
