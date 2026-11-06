
# BenBot web architecture (decided Oct 30, 2026)

## 1. Goal
A public site at https://bot.benlobaugh.com where visitors chat with BenBot, an AI that speaks as Ben (always labeled as an AI). Two front ends, one API: (a) a full chat page, (b) a widget (one script tag) that puts a chat bubble in the bottom-right corner of any page. Target embedders today: benlobaugh.com and ben.lobaugh.net.

## 2. Picture
```
Visitor browser  (bot.benlobaugh.com, or the widget on benlobaugh.com / ben.lobaugh.net)
   |
Cloudflare  (TLS, human challenges)
   |
Nginx Proxy Manager on the droplet   <- exists already, Ben configures it by hand, NOT in this repo
   |-- /      -> benbot_web   static chat page, /embed, /widget.js
   |-- /api   -> benbot_api   JSON API, owns the /api prefix (proxy never rewrites paths)
                    |-- SQLite file (volume): sessions, exchanges, flags
                    |-- vector index + private content/ (volumes; content read-only)
                    |-- benbot_embedder  Ollama + nomic-embed-text, INTERNAL network only
                    |-- chat model: PRIMARY connection, else SECONDARY
                          (Ollama on Ben's Mac and/or OpenRouter; either, both, or one)
benbot_backup : hourly SQLite snapshot -> DigitalOcean Spaces (private bucket)
benbot_ingest : one-off command that builds the index from content/ (manual)
```

## 3. Decisions
D1 Routing. One hostname, path routing: `/` to `benbot_web`, `/api` to `benbot_api`. The API serves ALL its routes under `/api` itself, so the same path works publicly (bot.benlobaugh.com/api/chat) and on the Docker network (http://benbot_api:PORT/api/chat). Ben creates the Nginx Proxy Manager entries by hand. How NPM forwards a custom location's path is UNVERIFIED: BENBOT-29 documents a test.
D2 Edge. Cloudflare in front, then the existing Nginx Proxy Manager. No proxy or TLS container in this repo.
D3 Stack. Python for the API and ingest (reuses all existing code). FastAPI + uvicorn unless the agent finds a verified reason to choose otherwise (record it). Web container: nginx serving plain HTML, CSS, and JavaScript with NO framework and NO build step. The widget is one vanilla JS file. Reason: understandability, and it is easier to write about.
D4 One pipeline. The API calls the existing `answer_turn` (guards, retrieval, prompt assembly, model call, verification with prune, retry, and fallback). Nothing reimplements it. The CLI and every eval keep working and keep calling it.
D5 No live token streaming for now. The visitor path generates the whole answer, verifies it, then shows it (BENBOT-13 decision). The API returns the finished reply as JSON; the UI shows a typing indicator. Streaming is an open item.
D6 Sessions and history. The server issues the session id (random, at least 128 bits). The browser stores only that id (localStorage, never cookies). The server stores the conversation in SQLite and builds the prompt history itself (sliding window of the last HISTORY_TURNS turns, existing setting). Idle timeout is configurable (SESSION_IDLE_MINUTES): after it the id is treated as expired and the next message starts a new session. A hard cap per session (SESSION_MAX_MESSAGES) ends it: the UI asks the visitor to start a new chat. No compaction or summarizing for now. A client-supplied unknown id never creates a session with that id.
D7 Logging. Every exchange is logged in full (visitor message, the reply as shown, outcome, scores, chunks, model connection used, timings) in SQLite and kept indefinitely. NO IP addresses, user agents, or other identifying data are stored. Anything a visitor types is stored as typed. The UI shows a visible notice. A delete-by-session command exists (deletions do not reach older backups; document that).
D8 Flagging is done in CODE, not by asking the model for a marker. The pipeline already has fixed lines and guards, so each turn gets a category (answered, no_answer, off_topic, guard_identity, guard_override, plus unavailable and error set by the API) and independent flags (weak_retrieval, repair_prune, repair_retry, repair_fallback, failover_used, truncated, injection_suspect). Content gaps (no_answer) are the most important to Ben. A CLI review tool lists them. Off-topic and suspected injection attempts are logged and viewable.
D9 Models. Two named connections, PRIMARY and SECONDARY, each an OpenAI-compatible endpoint (Ollama on Ben's Mac and/or OpenRouter). Either can be absent. Failover is automatic on connection failure, timeout, HTTP 429, or any 5xx. Other 4xx responses stay on that connection. The server flags that failover is in use and retries the primary after FAILOVER_RETRY_SECONDS (default 300). Both unreachable, or embedder unreachable: the visitor gets a friendly "not available right now" message (HTTP 503). There is no degraded mode. Which connection is primary is configuration. Temperature stays 0.
D10 Embeddings. Separate setting (EMBED_BASE_URL). `nomic-embed-text` in Ollama in the `benbot_embedder` container, reachable only on the internal Docker network, never published. Query and index must use the same model and prefixes (existing rule). The embedder does not fail over.
D11 Index and content. The NumPy index (decision in BENBOT-5) lives in a volume. Private markdown lives in a host directory mounted read-only. `about.md` is sent on every turn. Every other markdown file is searchable. The index is rebuilt by hand: `docker compose run --rm ingest`. No automated ingestion.
D12 Widget. `widget.js` draws a bubble (bottom-right on desktop) and opens an iframe to the chat's `/embed` route. One UI to maintain. Allowed embedders are set with a `frame-ancestors` header (benlobaugh.com and ben.lobaugh.net, configurable). Because the iframe is served from bot.benlobaugh.com, its calls to `/api` are same-origin, so CORS is OFF by default. On mobile the widget must look good (suggested: full-screen sheet).
D13 Protection. Cloudflare handles bot challenges. The app does NOT do per-IP rate limiting (it stores no IPs). In-app limits: message length cap, session cap, concurrency cap, global daily message cap. The OpenRouter spending cap is set by Ben in the OpenRouter dashboard.
D14 Backups. A backup container takes a consistent SQLite snapshot every hour (online backup or VACUUM INTO, never a copy of the live -wal/-shm files) and uploads it to a private DigitalOcean Spaces bucket. Retention configurable. A dead-man's-switch ping tells Ben if backups stop. A restore is tested.
D15 Delivery. Code in a PUBLIC GitHub repo (https://github.com/blobaugh/my-ai-rep; the bot is BenBot, the repository is my-ai-rep). A PRIVATE GitLab (Ben's) builds the images (linux/amd64) into its registry. The droplet has NO code checkout: only `docker-compose.yml`, `.env`, `content/`, and `data/`. Updates: `docker compose pull && docker compose up -d`. Ben sets up the droplet by hand.
D16 Repo. Public. Gitignored: `.env`, `content/`, `data/`, databases, eval results, and anything BENBOT-17 classifies private. `.env.example` has placeholders only. A small fictional example content set lives in `examples/`.
D17 Chat UI. Always visible label that this is an AI that speaks for Ben, an opening message, a logging notice, a footer showing the session id, text-only rendering (never HTML), mobile friendly.

## 4. One chat turn
1. Browser sends POST /api/chat with {session_id (optional), message}.
2. API validates: message length, daily cap, concurrency cap. Unknown or expired id: new session (new id returned). Session at its cap: reply `session_full`.
3. API writes the visitor message as a pending exchange and commits (no database lock is held while the model runs).
4. API loads the last HISTORY_TURNS turns and calls `answer_turn`: guards, retrieval (query embedded by the embedder), prompt, model on PRIMARY else SECONDARY, verification.
5. API updates the exchange with the reply, category, flags, scores, chunk ids, connection used, and timings, and commits.
6. API returns {session_id, reply, status}. Model or embedder unreachable: status `unavailable`, HTTP 503, friendly text, exchange logged with that status.

## 5. Containers and networks
- `benbot_web` (nginx): networks `proxy`. `benbot_api` (Python): `proxy` and `internal`. `benbot_embedder` (Ollama): `internal` only, no published ports. `benbot_backup`: no network needs except outbound to Spaces. `ingest` and the review tool run as one-off `docker compose run` commands from the api image.
- `proxy` is the existing external network Nginx Proxy Manager uses (name set in `.env`). `internal` is an internal-only network.
- Volumes (host bind mounts under BENBOT_HOME): `data/` (SQLite file, `index/`) and `content/` (read-only).

## 6. Settings (all read ONLY by `src/config.py`; names and defaults below are proposals the issues may finalize with a recorded reason)
LLM_PRIMARY_BASE_URL / _API_KEY / _MODEL / _TIMEOUT_SECONDS; LLM_SECONDARY_* (optional); FAILOVER_RETRY_SECONDS=300; EMBED_BASE_URL; DB_PATH; SESSION_IDLE_MINUTES=60; SESSION_MAX_MESSAGES=50; MESSAGE_MAX_CHARS=1000; MAX_CONCURRENT_TURNS; DAILY_MESSAGE_CAP; WEAK_RETRIEVAL_SCORE (unset until calibrated); CONTENT_DIR; FRAME_ANCESTORS; CORS_ALLOWED_ORIGINS (empty); CONTACT_URL (optional); backup settings. Existing LLM_BASE_URL / LLM_API_KEY / LLM_MODEL keep working as the PRIMARY connection when LLM_PRIMARY_* is unset. A blank value means unset.

## 7. Open items (not decided; do not decide silently)
1. Live streaming of replies (needs a different verification approach).
2. How the droplet reaches Ollama on Ben's Mac (Tailscale, a tunnel, or other). Ben sets this up; the app only needs a base URL. Ollama must never be exposed unauthenticated to the public internet.
3. Which connection is primary (Mac or OpenRouter): configuration only.
4. Droplet size and embedder speed on it: unmeasured.
5. Whether Ben's private GitLab has Container Registry and a runner that can build images: unverified.
6. Whether the bot may share Ben's contact email (the UI uses an optional CONTACT_URL meanwhile) and what it may say about family (project doc, Guardrails).
7. Whether `content/` is also backed up to Spaces (default off).
8. Exact wording of the AI label, opening message, and logging notice, including that messages are processed by third-party AI providers when OpenRouter is used.

## 8. Conventions for every issue
- Plain Python, small functions, type hints, ruff and pytest as configured. Tests use fakes and need no running Ollama or OpenRouter. Tests that need the private `content/` files SKIP when absent and use `examples/`.
- `src/config.py` is the only place that reads the environment. Blank value means unset. No secrets in code, logs, tests, or the repo. `.env.example` placeholders only. Never log IP addresses.
- One pipeline: do not reimplement retrieval, prompt assembly, the model call, or verification. Evals keep calling `answer_turn`.
- Do NOT change Ollama warm-up, keep-alive, or model loading. Do not change the default model or temperature (0). Do not weaken any guard or any verification behavior (BENBOT-13, BENBOT-15). Both fixed lines stay verbatim. Do not edit `content/` files or Q&A text.
- Verify current versions and APIs (FastAPI, Docker images, rclone or aws-cli, OpenRouter, Cloudflare, Nginx Proxy Manager) before relying on them, and say in the report what you could not verify.
- The repo is on git (BENBOT-17). Open BenBot work lands on `main` unless an issue says otherwise. Ben decided (Oct 30, 2026) to keep no archive copies of deleted learning scaffolding — deletions and overwrites are still permanent in history terms: work in small steps, run `scripts/check_public_safe.sh` before push, and check references before removing files.
- Spec changes need Ben's approval: put proposed spec text in the report instead of editing the spec.
- Report back as comments (Claude and Ben review from the comments without opening the repo): summary (at most 12 lines); pytest and ruff results; every file changed; the exact commands you ran to verify, with output; deviations and why; anything unverified or surprising; questions for Ben. Split comments over about 20,000 characters.
