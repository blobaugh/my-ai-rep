/** Pure chat rules. The page uses these; node --test checks them. */

export const NEAR_BOTTOM_PX = 80;

export const NETWORK_MESSAGE =
  "The message could not be sent. Please try again in a moment.";
export const TIMEOUT_MESSAGE =
  "That is taking too long. Please try again in a moment.";
export const WARMING_UP_MESSAGE = "Firing up the afterburners. One moment...";
export const WAITING_MESSAGE = "Waiting for a reply…";
export const STILL_THINKING_MESSAGE = "Still thinking…";
export const EMPTY_MESSAGE = "Please enter a message.";
export const TOO_LONG_MESSAGE = "That message is too long. Please shorten it.";
export const NEW_CONVERSATION = "A new conversation started.";

export const REQUEST_TIMEOUT_MS = 45000;
export const STILL_THINKING_MS = 8000;
export const REMAINING_WARN_WITHIN = 5;
export const COUNTER_SHOW_RATIO = 0.8;
export const COMPOSER_MAX_LINES = 6;

export function stripControls(text) {
  let kept = "";
  for (const char of text) {
    const code = char.codePointAt(0);
    if ((code === 9 || code === 10 || code === 13 || code >= 32) && code !== 127) {
      kept += char;
    }
  }
  return kept;
}

export function validateDraft(text, maxChars) {
  const cleaned = stripControls(String(text ?? ""));
  if (!cleaned.trim()) {
    return { ok: false, reason: "empty", message: EMPTY_MESSAGE, cleaned };
  }
  const limit = Number(maxChars);
  if (!Number.isFinite(limit) || limit < 1 || cleaned.length > limit) {
    return { ok: false, reason: "too_long", message: TOO_LONG_MESSAGE, cleaned };
  }
  return { ok: true, reason: "", message: "", cleaned };
}

export function safeHttpUrl(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  try {
    const url = new URL(value.trim());
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    return url.href;
  } catch {
    return "";
  }
}

/**
 * @param {string} sentSessionId id sent with this request, or ""
 * @param {number} httpStatus
 * @param {object | null} body
 */
export function interpretChat(sentSessionId, httpStatus, body) {
  const sent = typeof sentSessionId === "string" ? sentSessionId : "";
  if (!body || typeof body !== "object" || typeof body.status !== "string") {
    return {
      kind: "network",
      reply: NETWORK_MESSAGE,
      sessionId: sent,
      session: null,
      replaced: false,
      keepDraft: false,
      restart: false,
    };
  }
  const next =
    typeof body.session_id === "string" && body.session_id ? body.session_id : sent;
  const reply = typeof body.reply === "string" ? body.reply : NETWORK_MESSAGE;
  const kind = body.status;
  const replaced = Boolean(sent) && Boolean(next) && next !== sent;
  const session =
    body.session && typeof body.session === "object" ? body.session : null;
  return {
    kind,
    reply,
    sessionId: next,
    session,
    replaced,
    keepDraft: false,
    restart: kind === "session_full",
  };
}

/** Bot bubble for a successful answer; everything else is a system notice. */
export function outcomeStyle(kind) {
  return kind === "ok" ? "reply" : "notice";
}

/** True when the notice should offer Retry (session_full offers a new chat instead). */
export function isRetryable(kind) {
  return outcomeStyle(kind) === "notice" && kind !== "session_full";
}

/**
 * Hint when the session is within REMAINING_WARN_WITHIN of its cap.
 * @param {{ messages_used?: unknown, messages_max?: unknown } | null | undefined} session
 */
export function remainingHint(session) {
  if (!session || typeof session !== "object") return "";
  const used = Number(session.messages_used);
  const maximum = Number(session.messages_max);
  if (!Number.isFinite(used) || !Number.isFinite(maximum) || maximum < 1) return "";
  const left = maximum - used;
  if (left < 0 || left > REMAINING_WARN_WITHIN) return "";
  if (left === 0) return "No messages left in this chat.";
  if (left === 1) return "1 message left in this chat.";
  return `${left} messages left in this chat.`;
}

/** The model did not answer (cold start). The page says so and sends the message once more. */
export function shouldWarmRetry(outcome) {
  return Boolean(outcome) && outcome.kind === "unavailable";
}

/** True when the list is scrolled to (or within `slack` px of) its end. */
export function isNearBottom(scrollTop, clientHeight, scrollHeight, slack = NEAR_BOTTOM_PX) {
  return scrollHeight - scrollTop - clientHeight <= slack;
}

/**
 * Where to scroll so a new item is readable: the end of the list when the item fits,
 * otherwise the item's top so a long reply is read from its first line.
 */
export function revealScrollTop(itemTop, itemHeight, clientHeight, scrollHeight, gap = 8) {
  const end = Math.max(0, scrollHeight - clientHeight);
  if (itemHeight + gap <= clientHeight) return end;
  return Math.min(end, Math.max(0, itemTop - gap));
}

/** Show the character counter once the draft is near the limit. */
export function counterText(length, maxChars, ratio = COUNTER_SHOW_RATIO) {
  const used = Number(length);
  const maximum = Number(maxChars);
  if (!Number.isFinite(used) || !Number.isFinite(maximum) || maximum < 1) return "";
  if (used < maximum * ratio) return "";
  return `${used} / ${maximum}`;
}

/** Normalize starter questions from /api/config into a short unique list. */
export function normalizeStarters(value, limit = 6) {
  if (!Array.isArray(value)) return [];
  const found = [];
  const seen = new Set();
  for (const item of value) {
    if (typeof item !== "string") continue;
    const text = item.trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    found.push(text);
    if (found.length >= limit) break;
  }
  return found;
}

/**
 * Compact privacy notice: short summary, optional longer detail for "More".
 * @param {string} full
 * @param {string} [short]
 */
export function compactNotice(full, short = "") {
  const detail = String(full ?? "").trim();
  const summary = String(short ?? "").trim();
  if (!detail) return { summary: "", detail: "" };
  if (!summary || summary === detail) return { summary: detail, detail: "" };
  return { summary, detail };
}

/** Relative time label for message timestamps (hover/focus). */
export function relativeTime(then, now = Date.now()) {
  const at = Number(then);
  const current = Number(now);
  if (!Number.isFinite(at) || !Number.isFinite(current)) return "";
  const seconds = Math.max(0, Math.round((current - at) / 1000));
  if (seconds < 45) return "just now";
  if (seconds < 90) return "1 minute ago";
  const minutes = Math.round(seconds / 60);
  if (minutes < 45) return `${minutes} minutes ago`;
  if (minutes < 90) return "1 hour ago";
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} hours ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "1 day ago";
  return `${days} days ago`;
}

/** The only way a reply string becomes a DOM node: textContent. */
export function fillText(node, text) {
  node.textContent = String(text);
  return node;
}
