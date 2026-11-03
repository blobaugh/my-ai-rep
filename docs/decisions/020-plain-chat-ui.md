# A plain chat page, text only, session id in localStorage

**Status:** Accepted
**Date:** 2026-11-03
**Issue:** BENBOT-22

## Decision

The visitor chat is static files in `web/`. There is no framework, no bundler, and no dependency loaded from a network. `index.html` is the full page. `embed.html` is the same chat without extra page furniture, for the widget iframe. Both load `chat.js` as an ES module. Shared rules live in `logic.js` so `node --test` can run them without a browser.

Replies are written with `textContent` and nothing else. The model text is never parsed as HTML, markdown, or links. A reply that contains a tag shows the characters of the tag.

The browser stores one value, the session id, under `localStorage` key `benbot.sessionId`. Conversation text stays on the server. If storage throws (some embedded browsers block it), the id stays in memory for the life of the page. Cookies are not used: a cookie would be sent on every request, and this id is not an authentication secret the server needs to receive automatically.

The layout uses `dvh` so the column matches the visible viewport, including a mobile browser's collapsing toolbar. Tap targets are at least 44px. Colors follow `prefers-color-scheme`.

## What was not verified

iOS Safari was not available on this machine. `dvh` and the on-screen keyboard were not checked there. Desktop Chrome was.
