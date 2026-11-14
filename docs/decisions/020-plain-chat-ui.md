# A plain chat page, text only, session id in localStorage

**Status:** Accepted
**Date:** 2026-11-03
**Issue:** BENBOT-22

## Decision

The visitor chat is static files in `web/`. There is no framework, no bundler, and no dependency loaded from a network. `index.html` is the full page. `embed.html` is the same chat without extra page furniture, for the widget iframe. Both load `chat.js` as an ES module. Shared rules live in `logic.js` so `node --test` can run them without a browser.

Replies are written with `textContent` and nothing else. The model text is never parsed as HTML, markdown, or links. A reply that contains a tag shows the characters of the tag.

The session id lives in a page variable only. Nothing is written to `localStorage`, `sessionStorage`, or cookies. A reload or a new tab starts a fresh session. Conversation text stays on the server.

The page is a fixed `100dvh` column: the header (AI label, "New chat", "About") and the composer stay in place, and only the message list scrolls. A new message scrolls into view only when the reader is already at the end of the list, so scrolling up to read is not interrupted. A reply taller than the list is shown from its first line. Tap targets are at least 44px. Colors follow `prefers-color-scheme`.

## Amended 2026-11-13 (BENBOT-46)

The first version stored the session id under `localStorage` key `benbot.sessionId` but kept no transcript. After a reload the visitor saw an empty chat while the server still answered with the old history and counted the old messages toward `SESSION_MAX_MESSAGES`. Two tabs also shared, and overwrote, one id. Ben chose a fresh session per page load over a history endpoint or a client-side transcript cache.

Trade-off: the id shown under "About" for deletion requests is only available until the visitor leaves or reloads the page. The About text says so.

The page used to grow with the conversation (`min-height: 100dvh`), which pushed the newest reply and the composer below the fold, and in the widget's 556px iframe the footer covered the Send button. `web/dev/smoke.mjs` now checks, after ten exchanges at 375x667, 1280x800, 360x640 and the 380x556 embed, that the page does not grow, the composer and latest reply are visible, no header or composer controls overlap, a reader who scrolls up while waiting is not pulled down, and a reload shows only the opening message with no session id.

## What was not verified

iOS Safari was not available on this machine. `dvh` and the on-screen keyboard were not checked there. Desktop Chrome was.
