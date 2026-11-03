/** Pure chat rules. The page uses these; node --test checks them. */

export const SESSION_KEY = "benbot.sessionId";

export const NETWORK_MESSAGE =
  "The message could not be sent. Please try again in a moment.";
export const EMPTY_MESSAGE = "Please enter a message.";
export const TOO_LONG_MESSAGE = "That message is too long. Please shorten it.";
export const NEW_CONVERSATION = "A new conversation started.";

const KEEP_DRAFT = new Set([
  "unavailable",
  "busy",
  "daily_limit",
  "error",
  "invalid",
  "network",
]);

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
      replaced: false,
      keepDraft: true,
      restart: false,
    };
  }
  const next =
    typeof body.session_id === "string" && body.session_id ? body.session_id : sent;
  const reply = typeof body.reply === "string" ? body.reply : NETWORK_MESSAGE;
  const kind = body.status;
  const replaced = Boolean(sent) && Boolean(next) && next !== sent;
  return {
    kind,
    reply,
    sessionId: next,
    replaced,
    keepDraft: KEEP_DRAFT.has(kind) || httpStatus === 0,
    restart: kind === "session_full",
  };
}

export function createSessionStore(storage) {
  let memory = "";

  function attempt(fn) {
    try {
      return fn();
    } catch {
      return undefined;
    }
  }

  return {
    load() {
      const stored = attempt(() => storage.getItem(SESSION_KEY));
      if (typeof stored === "string" && stored) {
        memory = stored;
        return stored;
      }
      return memory;
    },
    save(id) {
      memory = typeof id === "string" ? id : "";
      if (!memory) {
        attempt(() => storage.removeItem(SESSION_KEY));
        return;
      }
      attempt(() => storage.setItem(SESSION_KEY, memory));
    },
    clear() {
      this.save("");
    },
  };
}

/** The only way a reply string becomes a DOM node: textContent. */
export function fillText(node, text) {
  node.textContent = String(text);
  return node;
}
