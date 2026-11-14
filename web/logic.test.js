import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  EMPTY_MESSAGE,
  NETWORK_MESSAGE,
  NEW_CONVERSATION,
  TIMEOUT_MESSAGE,
  TOO_LONG_MESSAGE,
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
  stripControls,
  validateDraft,
} from "./logic.js";

test("stripControls keeps tab and newline and drops other controls", () => {
  assert.equal(stripControls("a\u0000b\tc\nd\u007fe"), "ab\tc\nde");
});

test("validateDraft blocks empty and over-long text", () => {
  assert.deepEqual(validateDraft("  \n", 10), {
    ok: false,
    reason: "empty",
    message: EMPTY_MESSAGE,
    cleaned: "  \n",
  });
  const long = validateDraft("abcdef", 5);
  assert.equal(long.ok, false);
  assert.equal(long.reason, "too_long");
  assert.equal(long.message, TOO_LONG_MESSAGE);
  const ok = validateDraft("hello", 5);
  assert.equal(ok.ok, true);
  assert.equal(ok.cleaned, "hello");
});

test("interpretChat maps each API status", () => {
  const ok = interpretChat("", 200, {
    status: "ok",
    reply: "hi",
    session_id: "abc",
  });
  assert.equal(ok.kind, "ok");
  assert.equal(ok.keepDraft, false);
  assert.equal(ok.replaced, false);
  assert.equal(ok.sessionId, "abc");

  const expired = interpretChat("old", 200, {
    status: "ok",
    reply: "hi",
    session_id: "new",
  });
  assert.equal(expired.replaced, true);
  assert.equal(NEW_CONVERSATION.length > 0, true);

  for (const status of ["unavailable", "busy", "daily_limit", "error", "invalid"]) {
    const row = interpretChat("s", 500, { status, reply: status, session_id: "s" });
    assert.equal(row.keepDraft, false, status);
    assert.equal(row.restart, false, status);
    assert.equal(outcomeStyle(status), "notice", status);
    assert.equal(isRetryable(status), true, status);
  }

  const full = interpretChat("s", 409, {
    status: "session_full",
    reply: "full",
    session_id: "s",
  });
  assert.equal(full.restart, true);
  assert.equal(full.keepDraft, false);
  assert.equal(outcomeStyle("session_full"), "notice");
  assert.equal(isRetryable("session_full"), false);

  const down = interpretChat("s", 0, null);
  assert.equal(down.kind, "network");
  assert.equal(down.reply, NETWORK_MESSAGE);
  assert.equal(down.keepDraft, false);
  assert.equal(down.sessionId, "s");
  assert.equal(isRetryable("timeout"), true);
  assert.equal(TIMEOUT_MESSAGE.includes("too long"), true);
});

test("remainingHint warns only near the session cap", () => {
  assert.equal(remainingHint(null), "");
  assert.equal(remainingHint({ messages_used: 10, messages_max: 50 }), "");
  assert.equal(remainingHint({ messages_used: 45, messages_max: 50 }), "5 messages left in this chat.");
  assert.equal(remainingHint({ messages_used: 49, messages_max: 50 }), "1 message left in this chat.");
  assert.equal(remainingHint({ messages_used: 50, messages_max: 50 }), "No messages left in this chat.");
  assert.equal(outcomeStyle("ok"), "reply");
});

test("counterText appears only near the limit", () => {
  assert.equal(counterText(100, 1000), "");
  assert.equal(counterText(800, 1000), "800 / 1000");
  assert.equal(counterText(1000, 1000), "1000 / 1000");
});

test("normalizeStarters trims, dedupes, and caps", () => {
  assert.deepEqual(normalizeStarters(null), []);
  assert.deepEqual(
    normalizeStarters(["  One ", "Two", "One", "", 3, "Three", "Four", "Five", "Six", "Seven"]),
    ["One", "Two", "Three", "Four", "Five", "Six"],
  );
});

test("compactNotice keeps a short summary with optional detail", () => {
  assert.deepEqual(compactNotice(""), { summary: "", detail: "" });
  assert.deepEqual(compactNotice("Only one line."), {
    summary: "Only one line.",
    detail: "",
  });
  assert.deepEqual(compactNotice("Full notice text.", "Short notice."), {
    summary: "Short notice.",
    detail: "Full notice text.",
  });
});

test("relativeTime labels recent moments", () => {
  const now = 1_000_000;
  assert.equal(relativeTime(now - 1000, now), "just now");
  assert.equal(relativeTime(now - 120_000, now), "2 minutes ago");
});

test("only an unavailable model earns the warm-up retry", () => {
  assert.equal(WARMING_UP_MESSAGE.includes("afterburners"), true);
  const unavailable = interpretChat("s", 503, {
    status: "unavailable",
    reply: "not available",
    session_id: "s",
  });
  assert.equal(shouldWarmRetry(unavailable), true);
  for (const status of ["ok", "busy", "daily_limit", "error", "invalid", "session_full"]) {
    const row = interpretChat("s", 200, { status, reply: status, session_id: "s" });
    assert.equal(shouldWarmRetry(row), false, status);
  }
  assert.equal(shouldWarmRetry(interpretChat("s", 0, null)), false);
  assert.equal(shouldWarmRetry(null), false);
});

test("isNearBottom allows a small slack and rejects a reader scrolled up", () => {
  assert.equal(isNearBottom(600, 400, 1000), true);
  assert.equal(isNearBottom(530, 400, 1000), true);
  assert.equal(isNearBottom(500, 400, 1000), false);
  assert.equal(isNearBottom(0, 400, 1000), false);
  assert.equal(isNearBottom(0, 400, 300), true);
});

test("revealScrollTop goes to the end for a short item and to the top of a long one", () => {
  assert.equal(revealScrollTop(900, 60, 400, 1000), 600);
  assert.equal(revealScrollTop(500, 500, 400, 1000), 492);
  assert.equal(revealScrollTop(4, 900, 400, 1000), 0);
  assert.equal(revealScrollTop(0, 50, 400, 300), 0);
});

test("the page does not persist the session id", () => {
  const chat = readFileSync(new URL("./chat.js", import.meta.url), "utf8");
  assert.equal(/localStorage|sessionStorage|document\.cookie/.test(chat), false);
});

test("safeHttpUrl allows http(s) only", () => {
  assert.equal(safeHttpUrl("https://example.com/contact"), "https://example.com/contact");
  assert.equal(safeHttpUrl("javascript:alert(1)"), "");
  assert.equal(safeHttpUrl(""), "");
});

test("fillText writes textContent and not markup", () => {
  const node = { textContent: "" };
  const payload = "<img src=x onerror=alert(1)><script>alert(1)</script>";
  fillText(node, payload);
  assert.equal(node.textContent, payload);
  assert.equal("innerHTML" in node, false);
});

test("pages and scripts do not build HTML from strings", () => {
  const files = ["index.html", "embed.html", "chat.js", "styles.css", "logic.js"];
  for (const name of files) {
    const text = readFileSync(new URL(name, import.meta.url), "utf8");
    assert.equal(text.includes("innerHTML"), false, name);
    assert.equal(text.includes("insertAdjacentHTML"), false, name);
    assert.equal(/\son[a-z]+=/i.test(text), false, name);
    assert.equal(text.includes("javascript:"), false, name);
  }
  const index = readFileSync(new URL("index.html", import.meta.url), "utf8");
  const embed = readFileSync(new URL("embed.html", import.meta.url), "utf8");
  assert.match(index, /<script type="module" src="chat\.js"><\/script>/);
  assert.match(embed, /<script type="module" src="chat\.js"><\/script>/);
  assert.equal((index.match(/<script/g) || []).length, 1);
  assert.equal((embed.match(/<script/g) || []).length, 1);
});
