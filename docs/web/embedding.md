# Embedding the chat

Add one script tag. The file draws a bubble and, on the first open, an iframe to `/embed` on the same origin as the script. The host page does not call the API.

```html
<script src="https://bot.benlobaugh.com/widget.js" defer></script>
```

Remove the tag to take the bubble off the page. A session id already stored in the browser stays until the visitor clears site data for the chat origin.

## Options

Both are attributes on that script tag. Anything else is ignored.

| Attribute | Values | Default |
|---|---|---|
| `data-position` | `right` or `left` | `right` |
| `data-z-index` | a whole number | `2147483000` |

```html
<script src="https://bot.benlobaugh.com/widget.js" defer data-position="left"></script>
```

## Host page CSP

A host page with a strict Content-Security-Policy must allow the chat origin in:

- `script-src` (to load `widget.js`)
- `frame-src` (to load the `/embed` iframe)

The widget does not need `connect-src` on the host page. The iframe talks to `/api` on its own origin. Styles live in the shadow tree, so the host does not need `style-src` for this script.

## Who may frame `/embed`

The embed response sends `Content-Security-Policy: frame-ancestors` from `FRAME_ANCESTORS`. When that setting is blank, the list is `web/frame_ancestors.default`:

- `https://benlobaugh.com`
- `https://www.benlobaugh.com`
- `https://ben.lobaugh.net`

The full page `/` sends `frame-ancestors 'none'`. The template is `web/nginx.conf.template`. Render it with:

```bash
PYTHONPATH=. python web/dev/render_nginx.py
```

`widget.js` is served with `Cache-Control: public, max-age=300` and gzip. There is no build step, so the filename does not change. A new file reaches visitors within five minutes, or sooner if they reload.

A proxy that drops or duplicates `Content-Security-Policy` breaks the allowlist. That check belongs to BENBOT-29.

## The two sites

`benlobaugh.com` and `bot.benlobaugh.com` share a site, so the iframe is same-site there. `ben.lobaugh.net` is a different site. Browsers may partition `localStorage` for that cross-site iframe, which starts a fresh session more often. That is accepted (architecture D6).

What is known:

- `benlobaugh.com` is described as a one-page site.
- `ben.lobaugh.net` is a Payload CMS site.

What is not known, and was not changed here:

- The HTML template or build for `benlobaugh.com`, and the exact place to paste the tag.
- Which Payload layout or admin field should hold the tag on `ben.lobaugh.net`.

## Mobile

At 720px wide and below, the bubble is 48px and the open panel is a full-screen sheet. The page behind it does not scroll. Wider windows keep a 56px bubble and a 380 by 600 panel, including a wide touch screen. A full sheet on a touch laptop would cover the page the visitor is reading. That choice is easy to change.
