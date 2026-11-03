import {
  NEW_CONVERSATION,
  createSessionStore,
  fillText,
  interpretChat,
  safeHttpUrl,
  validateDraft,
} from "./logic.js";

const root = document.body;
const labelEl = document.querySelector("#ai-label");
const noticeEl = document.querySelector("#logging-notice");
const messagesEl = document.querySelector("#messages");
const form = document.querySelector("#composer");
const box = document.querySelector("#message");
const send = document.querySelector("#send");
const statusEl = document.querySelector("#status");
const newChat = document.querySelector("#new-chat");
const sessionEl = document.querySelector("#session-id");
const copyBtn = document.querySelector("#copy-id");
const contactRow = document.querySelector("#contact-row");
const contactLink = document.querySelector("#contact-link");

const sessions = createSessionStore(window.localStorage);
const apiBase = (root.dataset.apiBase || document.documentElement.dataset.apiBase || "").replace(/\/$/, "");

let maxChars = 1000;
let opening = "";
let waiting = false;

function api(path) {
  return `${apiBase}${path}`;
}

function setStatus(text) {
  fillText(statusEl, text);
}

function showSession(id) {
  fillText(sessionEl, id || "none yet");
  copyBtn.disabled = !id;
}

function addNote(text) {
  const note = document.createElement("p");
  note.className = "session-note";
  fillText(note, text);
  messagesEl.append(note);
}

function addMessage(role, text, restart) {
  const item = document.createElement("div");
  item.className = role === "visitor" ? "msg visitor" : "msg bot";
  const paragraph = document.createElement("p");
  fillText(paragraph, text);
  item.append(paragraph);
  if (restart) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "restart";
    fillText(button, "Start a new chat");
    button.addEventListener("click", () => resetChat());
    item.append(button);
  }
  messagesEl.append(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setTyping(on) {
  const current = messagesEl.querySelector(".typing");
  if (current) current.remove();
  if (!on) return;
  const item = document.createElement("div");
  item.className = "msg bot typing";
  const paragraph = document.createElement("p");
  fillText(paragraph, "Typing…");
  item.append(paragraph);
  messagesEl.append(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function resetChat() {
  sessions.clear();
  showSession("");
  messagesEl.replaceChildren();
  if (opening) addMessage("bot", opening, false);
  box.value = "";
  setStatus("");
  box.focus();
}

async function loadConfig() {
  const response = await fetch(api("/api/config"));
  if (!response.ok) throw new Error("config");
  const config = await response.json();
  maxChars = Number(config.max_message_chars) || 1000;
  opening = String(config.opening_message || "");
  const label = String(config.ai_label || "This is an AI.");
  fillText(labelEl, label);
  document.title = label;
  fillText(noticeEl, String(config.logging_notice || ""));
  const contact = safeHttpUrl(config.contact_url);
  if (contact) {
    contactLink.href = contact;
    contactRow.hidden = false;
  } else {
    contactRow.hidden = true;
  }
  messagesEl.replaceChildren();
  if (opening) addMessage("bot", opening, false);
  showSession(sessions.load());
}

async function sendMessage(text) {
  const sentId = sessions.load();
  const payload = { message: text };
  if (sentId) payload.session_id = sentId;
  waiting = true;
  send.disabled = true;
  setTyping(true);
  setStatus("");
  let httpStatus = 0;
  let body = null;
  try {
    const response = await fetch(api("/api/chat"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    httpStatus = response.status;
    body = await response.json();
  } catch {
    httpStatus = 0;
    body = null;
  }
  const outcome = interpretChat(sentId, httpStatus, body);
  setTyping(false);
  if (outcome.replaced) addNote(NEW_CONVERSATION);
  addMessage("visitor", text, false);
  addMessage("bot", outcome.reply, outcome.restart);
  if (outcome.sessionId) {
    sessions.save(outcome.sessionId);
    showSession(outcome.sessionId);
  }
  if (outcome.keepDraft) box.value = text;
  else box.value = "";
  waiting = false;
  send.disabled = false;
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

newChat.addEventListener("click", () => resetChat());

copyBtn.addEventListener("click", async () => {
  const id = sessions.load();
  if (!id) return;
  try {
    await navigator.clipboard.writeText(id);
    setStatus("Copied the session id.");
  } catch {
    setStatus("Copy failed. Select the session id and copy it yourself.");
  }
});

showSession(sessions.load());
loadConfig().catch(() => {
  fillText(labelEl, "This is an AI.");
  setStatus("The chat settings could not be loaded.");
});
