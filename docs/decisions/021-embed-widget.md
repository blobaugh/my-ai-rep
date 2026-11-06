# The widget is one script and an iframe

**Status:** Accepted
**Date:** 2026-11-03
**Issue:** BENBOT-23

## Decision

`web/widget.js` is a classic script with no dependencies. It reads its own `src` to find the chat origin, draws a bubble in a shadow tree, and creates the `/embed` iframe on the first open. The host page does not receive conversation text.

`/embed` may be framed only by origins in `FRAME_ANCESTORS`. A blank setting reads `web/frame_ancestors.default` (may be empty comments only); **config** and the **Docker web entrypoint** then fall back to `http://127.0.0.1:8080` and `http://localhost:8080` so local stacks start. The full page sends `frame-ancestors 'none'`. The nginx template is rendered by substituting that list. The image itself is BENBOT-24.

The default file names `https://ben.lobaugh.net`. That string is kept out of `src/` because the public-source check rejects it there. The setting is still read only by `src/config.py`.

On a narrow window the panel becomes a full-screen sheet. A wide touch screen keeps the smaller panel.

`widget.js` is cached for five minutes. There is no hashed filename because there is no build.

## What was not verified

Safari and Firefox were not automated. The Chrome storage check is in the BENBOT-23 work log. Payload and the one-page site were not edited.
