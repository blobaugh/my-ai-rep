# Embedding the chat widget

The widget is a single file, `widget.js`, served by the web container. Add one script tag on any page that is allowed to frame the chat origin’s `/embed` route.

## Install

```html
<script src="https://YOUR-CHAT-HOST/widget.js" defer></script>
```

Optional: `data-position="left"` and `data-z-index="2147483000"` on the script tag (see `web/widget.js`).

## JavaScript API

The script exposes **`window.PersonaChatWidget`** with helpers (`chatOrigin`, `readOptions`, `sheetForWidth`) and sets `mounted` when the bubble is on the page. For backward compatibility, **`window.BenBotWidget`** is an alias to the same object (deprecated).

The host element uses **`data-persona-chat-widget`** (legacy: `data-benbot-widget` is not set; migrate selectors).

## Frame ancestors

The `/embed` response sends `Content-Security-Policy: frame-ancestors …`. Allowed origins come from `FRAME_ANCESTORS` or `web/frame_ancestors.default`. In Docker, if both are empty, the entrypoint defaults to `http://127.0.0.1:8080` and `http://localhost:8080` so local widget tests work; **set `FRAME_ANCESTORS` in production** to your real sites.

## Example with concrete hostnames (historical)

See [`../history/embedding-operator-deployment.md`](../history/embedding-operator-deployment.md) for a worked example from an early deployment.
