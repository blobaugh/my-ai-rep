# Protection limits (app layer)

BenBot uses three layers: **Cloudflare** (bot challenges for humans), **in-app
caps** (this document), and **OpenRouter spending limits** on the paid model key.

The app stores **no IP addresses** and does no per-IP rate limiting.

## Settings

| Setting | Default | Visitor experience |
|---------|---------|-------------------|
| `MESSAGE_MAX_CHARS` | 1000 | 400 if over limit |
| `SESSION_MAX_MESSAGES` | 50 | 409 `session_full` |
| `MAX_CONCURRENT_TURNS` | 2 | 429 `busy` after `BUSY_WAIT_SECONDS` (3s) |
| `DAILY_MESSAGE_CAP` | 300 | 429 `daily_limit`; `0` disables |
| `BUSY_WAIT_SECONDS` | 3 | Wait for a pipeline slot before `busy` |
| `CONTACT_URL` | unset | Appended to `daily_limit` text when set |

**Defaults rationale:** Two concurrent turns match a single embedder plus one
chat stream on a small droplet without queueing every visitor behind a long
generation. Three hundred messages per UTC day is a generous ceiling for a
personal bot while bounding runaway spend if Cloudflare misses something.

## HTTP hardening

- Request body max **8192 bytes** before JSON parse.
- `Content-Type: application/json` required on `POST /api/chat`.
- Control characters stripped from the message (tabs/newlines kept).
- `Cache-Control: no-store` on chat responses.
- `X-Content-Type-Options: nosniff` on all `/api/*` responses.
- Uvicorn `timeout_keep_alive=5` (see `src/api/__main__.py`).

## Logging

Application logs emit one JSON line per chat outcome with `request_id`, `status`,
`http`, and optional `category`. Visitor text, secrets, and IPs are never logged.

## Provider limits

HTTP **402** or **429** from a chat provider logs `provider limit signal` and
adds flag `provider_limit` on the stored turn when the API returns unavailable.
Failover behavior is unchanged (BENBOT-18).

## OpenRouter spend cap

In the OpenRouter dashboard, open **Settings → Credits** (or **Billing**) and set
a monthly credit limit or purchase a fixed credit bundle for the API key BenBot
uses. Exact menu names change; verify against https://openrouter.ai/docs when
deploying. This agent could not re-verify live UI labels in Nov 2026.

## Cloudflare (optional)

On the free plan, **Security → WAF** may offer basic bot fight mode; **Rules →
Rate limiting** is often a paid feature. A common pattern is a challenge on
`POST /api/chat` for anonymous traffic. Verify current plan features in the
Cloudflare dashboard — not re-verified here.

## Busy vs daily limit

Neither limit creates a SQLite session row. They are checked before `begin_turn`.
