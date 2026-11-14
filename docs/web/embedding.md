# Embedding the chat widget

The widget is a single file, `widget.js`, served by the web container. Add one script tag on any page that is allowed to frame the chat origin’s `/embed` route.

## Install

```html
<script src="https://YOUR-CHAT-HOST/widget.js" defer></script>
```

Optional attributes on the script tag:

| Attribute | Effect |
| --- | --- |
| `data-position="left"` | Launcher on the left (default: right) |
| `data-z-index="2147483000"` | Stacking order (digits only) |
| `data-title="BenBot is an AI"` | Widget header title (skips `/api/config`) |
| `data-label="Chat"` | Text pill launcher instead of the icon |
| `data-aria-label="Open BenBot"` | Accessible name for the launcher |

Without `data-title`, the widget fetches public `/api/config` and uses `ai_label` (or `{bot_name} is an AI`). That fetch is cross-origin from the host page, so include the host in `CORS_ALLOWED_ORIGINS` (or set `data-title` and skip the fetch). The iframe loads `/embed?widget=1` so the page hides its duplicate AI label; the widget header carries the disclosure.

## JavaScript API

The script exposes **`window.PersonaChatWidget`** with helpers (`chatOrigin`, `readOptions`, `sheetForWidth`, `headerTitle`) and sets `mounted` when the bubble is on the page. For backward compatibility, **`window.BenBotWidget`** is an alias to the same object (deprecated).

The host element uses **`data-persona-chat-widget`** (legacy: `data-benbot-widget` is not set; migrate selectors).

## Frame ancestors

The `/embed` response sends `Content-Security-Policy: frame-ancestors …`. Allowed origins come from `FRAME_ANCESTORS` or `web/frame_ancestors.default`. In Docker, if both are empty, the entrypoint defaults to `http://127.0.0.1:8080` and `http://localhost:8080` so local widget tests work; **set `FRAME_ANCESTORS` in production** to your real sites.

## Example with concrete hostnames (historical)

See [`../history/embedding-operator-deployment.md`](../history/embedding-operator-deployment.md) for a worked example from an early deployment.
