# Run the stack on a DigitalOcean droplet (Docker, git clone)

This walkthrough assumes you already have a **DigitalOcean droplet** running **Ubuntu**
with **Docker** and the **Compose plugin** installed and working. It does **not** cover
creating the droplet, installing Docker, DNS, TLS, or reverse proxies.

Everything runs from a **git clone** of this repository: you **build** images from the
checkout (no separate registry flow). The chat model is configured **only through `.env`**
(OpenAI-compatible HTTP API). This tutorial does **not** cover installing or operating
Ollama on the droplet itself; the **embedder** service is still part of the Compose stack
and handles vectors inside its container (see [containers.md](../web/containers.md)).

Optional: S3-compatible object storage for backups — see [backup-restore.md](../deploy/backup-restore.md).

## What you are running

From the repo root ([architecture.md](../web/architecture.md)):

- **`benbot_web`** — static chat UI, `/embed`, `widget.js` (listens on **8080** inside the container).
- **`benbot_api`** — FastAPI on `/api/*` (listens on **8000** inside the container).
- **`benbot_embedder`** — embeddings for ingest and chat retrieval (internal network).
- **`ingest`** — one-shot index build (`--profile tools`).
- Optional **`benbot_backup`** when you enable Spaces env vars (not required for the first run).

Persistent data on the host:

- `data/` — SQLite log and NumPy index (gitignored).
- `content/` or `examples/` — markdown the bot may cite.

## 1. Clone on the droplet

```bash
git clone <YOUR_REPOSITORY_URL> benbot
cd benbot
export BENBOT_HOME="$PWD"
```

All later commands use this directory.

## 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` for a headless server. At minimum, point the **chat** model at an API you
control (OpenRouter, hosted OpenAI-compatible endpoint, etc.):

```bash
# Example shape — use your own URL, key, and model id
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=your-key-here
LLM_MODEL=openai/gpt-4o-mini

BOT_NAME=Bot
HUMAN_NAME=
```

Other keys are documented in [`.env.example`](../../.env.example) and grouped in the
root [README.md](../../README.md#configuration-reference). `src/config.py` is the only
reader. **`docker-compose.checkout.yml` does not set LLM variables** — only `.env` does.

## 3. Content and ingest

First runs can use the fictional sample tree:

```bash
mkdir -p data
# examples/ is in git — dev compose mounts it at /content
```

Build and start the stack, then build the index:

```bash
scripts/checkout-up.sh -d
docker compose -f docker-compose.yml -f docker-compose.checkout.yml --profile tools run --rm ingest
```

`docker-compose.checkout.yml` builds **linux/amd64** images from the checkout, **does not
publish host ports** (NPM reaches containers on the external **`web`** network), and mounts
`examples/` as `/content`. Ensure that network exists (`docker network ls`; create it if
your proxy stack has not yet). Set `PROXY_NETWORK` in `.env` when the name differs. For
private markdown, copy files into `content/` and adjust mounts per [content.md](../deploy/content.md).

For your own markdown later, add files under `content/` and adjust mounts per
[content.md](../deploy/content.md).

## 4. Smoke checks

Through the hostname you configured in NPM (same paths as production):

```bash
curl -sS https://YOUR_HOST/api/health
```

Or from the droplet on the Docker **`web`** network (no host port publish):

```bash
docker run --rm --network web curlimages/curl:latest -sS http://benbot_api:8000/api/health
docker run --rm --network web curlimages/curl:latest -sS http://benbot_web:8080/
```

Chat (see [api.md](../web/api.md); use your public `/api` URL or `benbot_api:8000` on `web`):

```bash
curl -sS -X POST https://YOUR_HOST/api/chat \
  -H 'content-type: application/json' \
  -d '{"message":"Who are you?"}'
```

The JSON body includes `status`, `reply`, `session_id`, and `session` usage. It does
**not** include the pipeline **category** (next section).

Open the UI in a browser at the hostname NPM serves for `benbot_web`.

## 5. Optional: widget

If another site should frame the chat, set `FRAME_ANCESTORS` in `.env` and read
[embedding.md](../web/embedding.md). Default embed allowances are described there and in
`.env.example`.

## 6. Optional: backups

To run the backup sidecar against real object storage, set `SPACES_*` and related vars in
`.env` and follow [backup-restore.md](../deploy/backup-restore.md). The dev merge can use
local MinIO/Silo for experiments; that is optional.

## 7. Turn categories and the review CLI

Each **successful** chat turn is classified in code into exactly one **category**:

| Category | Typical meaning |
| --- | --- |
| `answered` | Reply is treated as grounded in your content |
| `no_answer` | Fixed “missing detail” style reply — content gap |
| `off_topic` | Fixed off-topic redirect |
| `guard_identity` | Identity guard (e.g. “Are you human?”) |
| `guard_override` | Override / injection-style guard |

These values come from `src/outcomes.py` and are stored in SQLite (`DB_PATH`, default
`data/benbot.sqlite`). They are **not** returned in the public `POST /api/chat` JSON; use
the review tool to inspect them. Full command reference: [review.md](../web/review.md).

### Run review against the live database

While containers are up:

```bash
docker compose run --rm api python -m src.review stats
```

From the host (same `DB_PATH` as the api container mount):

```bash
python -m src.review stats
```

### Commands by category

**Content gaps (`no_answer`)** — find questions the bot could not answer from markdown:

```bash
docker compose run --rm api python -m src.review gaps
docker compose run --rm api python -m src.review list --category no_answer --limit 20
```

**Grounded replies:**

```bash
docker compose run --rm api python -m src.review list --category answered --limit 20
```

**Off-topic:**

```bash
docker compose run --rm api python -m src.review offtopic --limit 20
```

**Guards** (`guard_identity`, `guard_override`, plus injection flag):

```bash
docker compose run --rm api python -m src.review suspect --limit 20
docker compose run --rm api python -m src.review list --category guard_identity --limit 10
docker compose run --rm api python -m src.review list --category guard_override --limit 10
```

**One session in full context** (category, flags, retrieval, repair):

```bash
docker compose run --rm api python -m src.review show <session-id>
```

Use the `session_id` from a chat JSON response or from `list` output.

**Export** for spreadsheets or notes:

```bash
docker compose run --rm api python -m src.review list --category no_answer \
  --out /app/data/gaps.csv --format csv
```

The file lands under `data/` on the host because of the volume mount.

### Close the loop

1. Run `gaps` after some real questions.
2. Add or fix markdown under `content/` (or `examples/` while learning).
3. Re-run ingest: `docker compose --profile tools run --rm ingest`.
4. Ask the same question again and use `list --category …` or `show` to confirm the
   category moved toward `answered` when content supports it.

## 8. Troubleshooting

| Symptom | Check |
| --- | --- |
| `unavailable` / 503 chat | `.env` LLM URL and key; api logs: `docker compose logs api` |
| Health 503 | Index missing — run ingest; embedder health: `docker compose ps` |
| Build fails on `platform` | Checkout file targets **amd64**; arm64 hosts need a forked platform line |
| `network web declared as external, but could not be found` | Create the network your proxy uses, or set `PROXY_NETWORK` in `.env` |
| Review: database not found | `DB_PATH` and host `data/` mount match the running api container |

More rows: [troubleshooting.md](../deploy/troubleshooting.md).

## 9. Privacy (short)

Visitor messages and replies are stored in SQLite. The UI shows a logging notice from
`/api/config`. If `LLM_*` points at a hosted provider, visitor text leaves your droplet
for that API. Details: [018-sqlite-store.md](../decisions/018-sqlite-store.md) and the root
README privacy section.
