# Production verification checklist

Run top to bottom after deploy or material config change. Replace
`https://bot.benlobaugh.com` with your hostname.

**Legend:** commands marked **(droplet)** run on the server; **(Mac)** from your laptop.

---

## 1. TLS and static site **(Mac)**

```bash
curl -sI https://bot.benlobaugh.com/
```

Expect: `HTTP/2 200` (or `301` once to canonical), `content-type: text/html`, no obvious
cache of API on `/`.

## 2. API health **(Mac)**

```bash
curl -sS https://bot.benlobaugh.com/api/health
```

Expect: JSON with a healthy status (same shape as local `/api/health`).

## 3. Chat session (two messages) **(Mac)**

```bash
SESSION=$(curl -sS -D - -o /tmp/benbot_chat1.json \
  -H 'Content-Type: application/json' \
  -d '{"message":"Say hello in one short sentence."}' \
  https://bot.benlobaugh.com/api/chat | awk '/^Set-Cookie:/ {print $2}' | tr -d '\r')

curl -sS -H 'Content-Type: application/json' -H "Cookie: $SESSION" \
  -d '{"message":"What did I just ask you?"}' \
  https://bot.benlobaugh.com/api/chat | head -c 500
echo
```

Expect: first response sets a session cookie; second response references the prior turn.
If you get HTML instead of JSON, NPM path routing is wrong ([droplet-setup.md](./droplet-setup.md)).

## 4. Embed framing policy **(Mac)**

```bash
curl -sI https://bot.benlobaugh.com/embed | grep -i content-security-policy
```

Expect: `frame-ancestors` listing your allowed sites (from `FRAME_ANCESTORS` / default file).
**UNVERIFIED** until tested with Cloudflare enabled — duplicate or missing CSP breaks the widget.

## 5. Widget asset **(Mac)**

```bash
curl -sI https://bot.benlobaugh.com/widget.js
```

Expect: `200`, `content-type: application/javascript` or `text/javascript`.

## 6. Embedder not public **(Mac + droplet)**

**(droplet)**

```bash
docker port benbot_embedder
# expect: no output
```

**(Mac)** — from outside the firewall:

```bash
nc -vz YOUR_DROPLET_IP 11434
# expect: connection refused or timed out (not open)
```

## 7. Widget on pages **(Mac, manual)**

- Load a test HTML page that includes `widget.js` from production.
- Confirm chat opens on **both** production sites that should embed BenBot.
- Browser devtools: no CSP `frame-ancestors` violations.

## 8. Failover **(droplet + Mac)**

Stop Ollama on the Mac (or block primary URL). Send a chat message via HTTPS.

Then **(droplet)**:

```bash
docker compose --profile tools run --rm api python -m src.review failovers --since 24h
```

Expect: a recent failover row with secondary provider use.

Restore primary afterward.

## 9. Backup **(droplet)**

Follow [backup-restore.md](./backup-restore.md): confirm a new object in Spaces after
the hourly window, and that `BACKUP_PING_URL` received a ping if configured.

## 10. Review tool **(droplet)**

```bash
docker compose --profile tools run --rm api python -m src.review stats
docker compose --profile tools run --rm api python -m src.review list --limit 5
```

Expect: stats without error; recent sessions if traffic exists.

---

## Dev stack equivalent (agent / laptop)

With `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`:

```bash
./scripts/verify-deploy-local.sh
curl -fsS http://127.0.0.1:8080/api/health
curl -fsSI http://127.0.0.1:8080/embed | grep -i content-security-policy
```

**Validated in repo (2026-11-03):** commands syntax-checked; full `./scripts/verify-docker.sh`
run requires Docker + embedder model pull (slow). Use when changing compose or images.

---

## Droplet-only sign-off

Before calling production healthy, Ben confirms:

- [ ] NPM `/api` forwarding (step 3 returns JSON, not HTML)
- [ ] Cloudflare SSL mode + CSP header (step 4 with orange cloud)
- [ ] Widget on live sites (step 7)
- [ ] Failover with real Mac primary (step 8)
- [ ] Spaces backup + optional ping (step 9)
