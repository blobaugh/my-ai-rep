import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  EMPTY_MESSAGE,
  NETWORK_MESSAGE,
  NEW_CONVERSATION,
  SESSION_KEY,
  TOO_LONG_MESSAGE,
  createSessionStore,
  fillText,
  interpretChat,
  safeHttpUrl,
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
    assert.equal(row.keepDraft, true, status);
    assert.equal(row.restart, false, status);
  }

  const full = interpretChat("s", 409, {
    status: "session_full",
    reply: "full",
    session_id: "s",
  });
  assert.equal(full.restart, true);
  assert.equal(full.keepDraft, false);

  const down = interpretChat("s", 0, null);
  assert.equal(down.kind, "network");
  assert.equal(down.reply, NETWORK_MESSAGE);
  assert.equal(down.keepDraft, true);
  assert.equal(down.sessionId, "s");
});

test("session store uses one key and survives a blocked storage", () => {
  const saved = new Map();
  const storage = {
    getItem(key) {
      return saved.has(key) ? saved.get(key) : null;
    },
    setItem(key, value) {
      saved.set(key, value);
    },
    removeItem(key) {
      saved.delete(key);
    },
  };
  const store = createSessionStore(storage);
  assert.equal(store.load(), "");
  store.save("abc");
  assert.equal(saved.get(SESSION_KEY), "abc");
  assert.deepEqual([...saved.keys()], [SESSION_KEY]);
  assert.equal(store.load(), "abc");
  store.clear();
  assert.equal(saved.has(SESSION_KEY), false);
  assert.equal(store.load(), "");

  const blocked = createSessionStore({
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    },
    removeItem() {
      throw new Error("blocked");
    },
  });
  blocked.save("mem");
  assert.equal(blocked.load(), "mem");
  blocked.clear();
  assert.equal(blocked.load(), "");
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
