# BenBot

BenBot is a small web app that lets visitors chat with an AI speaking in my voice,
grounded in markdown I wrote about myself. I built it as a **learning project**:
prompting, retrieval, verification, containers, and the messy parts of running a
real LLM behind HTTP.

The public git repo is [`my-ai-rep`](https://github.com/blobaugh/my-ai-rep); the
product name is **BenBot**. Same codebase, two names — the repo is generic, the
bot is mine.

Screenshots (chat page and widget) live under [`docs/web/screenshots/e2e/`](docs/web/screenshots/e2e/)
after you run the optional Playwright e2e tests (`docs/web/e2e.md`).

## What is in this repo

- Python API, ingest, retrieval, evals, and review tools (`src/`)
- Plain HTML/CSS/JS chat UI and embeddable widget (`web/`)
- Docker Compose for local dev and production pull-only layout
- Fictional sample content (`examples/`) you can index without private files
- Decision records and deployment runbooks (`docs/`)

## What is deliberately not here

- **`content/`** — my real notes and Q&A (gitignored)
- **`data/`** — SQLite log and vector index (gitignored)
- **`.env`** — keys and local overrides (gitignored; see `.env.example`)
- **Voice samples** and other private prompts listed in `.gitignore`

Before publishing, run `scripts/check_public_safe.sh` (see [Public git](#public-git)).

## Architecture (one picture)

From [`docs/web/architecture.md`](docs/web/architecture.md):

```
Visitor browser  (chat page or widget iframe)
   |
   |  local dev: http://127.0.0.1:8080  (web proxies /api to the api container)
   |
benbot_web  (static files, /embed, widget.js)
benbot_api  (FastAPI, /api/*, sessions in SQLite)
   |-- vector index + content mount
   |-- benbot_embedder  (Ollama + nomic-embed-text, internal network only)
   |-- PRIMARY / SECONDARY chat models (Ollama and/or OpenRouter)
benbot_backup  (hourly SQLite snapshots to object storage, in production)
```

### One chat turn (short)

1. Browser `POST /api/chat` with `{ "message", "session_id"? }`.
2. API validates length, concurrency, and daily caps; resolves the session ([`docs/decisions/018-sqlite-store.md`](docs/decisions/018-sqlite-store.md)).
3. `answer_turn` runs guards, embeds the query, retrieves chunks, builds the prompt, calls the model, verifies the draft ([`docs/decisions/007-prompt-layout.md`](docs/decisions/007-prompt-layout.md), [`docs/decisions/016-llm-failover.md`](docs/decisions/016-llm-failover.md)).
4. The reply, category, flags, and retrieval metadata are stored; JSON goes back to the browser ([`docs/decisions/019-http-api.md`](docs/decisions/019-http-api.md)).

Why it looks like this: a **NumPy file index** instead of a vector DB ([`docs/decisions/003-numpy-file-vector-store.md`](docs/decisions/003-numpy-file-vector-store.md)), **no front-end framework** ([`docs/decisions/020-plain-chat-ui.md`](docs/decisions/020-plain-chat-ui.md)), **verification in code** (not “please follow the rules”), **server-side session history**, and **no token streaming** yet ([`docs/web/architecture.md`](docs/web/architecture.md) D5).

## Quick start (sample content, no private `content/`)

These steps assume **Python 3.9+** and **[Ollama](https://ollama.com/download)** installed on your machine.

```bash
git clone https://github.com/blobaugh/my-ai-rep.git
cd my-ai-rep

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env
# Optional: BOT_NAME= and HUMAN_NAME= for greetings

ollama pull llama3.1:8b
ollama pull nomic-embed-text

export CONTENT_DIR=examples
python -m src.ingest
python -m src.chat --ask "Who are you?"
```

You should get a first-person answer about the fictional sample persona (Avery Quinn in `examples/`).

### Web UI (Docker dev stack)

Requires Docker. Builds local images and opens the app on port 8080.

```bash
scripts/dev-up.sh
# wait for healthy containers, then in another terminal:
docker compose --profile tools run --rm ingest
```

Open http://127.0.0.1:8080/ . The dev stack mounts `examples/` as `/content` automatically (`docker-compose.dev.yml`).

End-to-end tests (optional): `./scripts/e2e.sh` — see [`docs/web/e2e.md`](docs/web/e2e.md).

## Add your own content

Layout ([BENBOT-36](docs/spec/benbot-behavior.md)):

| File | Role |
| --- | --- |
| `content/about.md` | Always included in the prompt. **Not** embedded or searched. |
| Every other `*.md` under `content/` | Searchable. Prose splits on headings; optional Q&A uses `##` / `Q:` / `A:` ([`docs/decisions/010-qa-format.md`](docs/decisions/010-qa-format.md)). |

Copy from [`examples/`](examples/) or write your own, then:

```bash
python -m src.ingest
python -m src.retrieve "What kind of work do you do?"
```

Review conversations and content gaps: [`docs/web/review.md`](docs/web/review.md).

## Swap models

All connection settings go through `.env` (read only in [`src/config.py`](src/config.py)):

- **Local Ollama:** `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (defaults target `http://localhost:11434/v1` and `llama3.1:8b`).
- **Named primary:** set all of `LLM_PRIMARY_BASE_URL`, `LLM_PRIMARY_API_KEY`, `LLM_PRIMARY_MODEL` to override the legacy trio.
- **Failover:** set all of `LLM_SECONDARY_*` (for example OpenRouter). See [`docs/decisions/016-llm-failover.md`](docs/decisions/016-llm-failover.md).

Compare candidates before switching:

```bash
python -m eval.compare_models
```

Details: [`docs/decisions/024-openrouter-model-eval.md`](docs/decisions/024-openrouter-model-eval.md).

Stock `llama3.1:8b` has a small context window; this repo documents a larger derived model in [`docs/decisions/008-context-window.md`](docs/decisions/008-context-window.md).

## Configuration reference

Every setting below is loaded by `src/config.py`. Blank usually means “unset”. Grouped for reading; defaults match a fresh `.env.example`.

### Models and failover

| Setting | Default | Meaning |
| --- | --- | --- |
| LLM_BASE_URL | http://localhost:11434/v1 | Primary chat API when `LLM_PRIMARY_*` is unset |
| LLM_API_KEY | ollama | Primary API key |
| LLM_MODEL | llama3.1:8b | Primary model id |
| LLM_PRIMARY_BASE_URL | unset | Optional primary group (with `_API_KEY`, `_MODEL`) |
| LLM_PRIMARY_API_KEY | unset | Primary key when group is set |
| LLM_PRIMARY_MODEL | unset | Primary model when group is set |
| LLM_PRIMARY_TIMEOUT_SECONDS | 120 | Total seconds for one primary request |
| LLM_SECONDARY_BASE_URL | unset | Failover endpoint (set all three secondary vars or none) |
| LLM_SECONDARY_API_KEY | unset | Secondary key |
| LLM_SECONDARY_MODEL | unset | Secondary model |
| LLM_SECONDARY_TIMEOUT_SECONDS | 120 | Secondary total timeout |
| FAILOVER_RETRY_SECONDS | 300 | Seconds before retrying primary after failover |
| FAILOVER_ON_HTTP_STATUS | unset | Extra HTTP statuses that trigger failover (429 and 5xx already do) |
| LLM_TEMPERATURE | 0 | Chat temperature |
| LLM_MAX_TOKENS | 600 | Max completion tokens |

### Embeddings

| Setting | Default | Meaning |
| --- | --- | --- |
| EMBED_MODEL | nomic-embed-text | Embedding model name |
| EMBED_BASE_URL | http://localhost:11434/v1 | Embedding API base |
| EMBED_API_KEY | ollama | Embedding API key |
| EMBED_BATCH_SIZE | 32 | Batch size for ingest |
| EMBED_MAX_CHARS | 8000 | Max characters per embedded document |
| EMBED_QUERY_PREFIX | search_query: | Query prefix for nomic-embed-text |
| EMBED_DOC_PREFIX | search_document: | Document prefix |
| QA_EMBED_MODE | multi | How Q&A entries are embedded ([`docs/decisions/011-qa-embed-mode.md`](docs/decisions/011-qa-embed-mode.md)) |

### Retrieval and prompt

| Setting | Default | Meaning |
| --- | --- | --- |
| RETRIEVAL_K | 4 | Chunks retrieved per turn |
| RETRIEVAL_MAX_PER_ARTICLE | 2 | Cap per source file |
| RETRIEVAL_MIN_SCORE | unset | Optional cosine floor |
| WEAK_RETRIEVAL_SCORE | unset | Flag weak retrieval below this score |
| RETRIEVAL_QUERY_MODE | auto | `auto` or `turns` for query text |
| RETRIEVAL_QUERY_TURNS | 2 | User turns joined when mode is `turns` |
| HISTORY_TURNS | 6 | Server-side history window |
| CONTEXT_BUDGET_TOKENS | 7000 | Prompt token budget (heuristic) |
| VOICE_SAMPLES | off | Include optional voice samples in prompt |
| CONTENT_DIR | content | Markdown root (`examples` for samples) |
| BOT_NAME | Bot | Bot label in copy |
| HUMAN_NAME | empty | Persona name in copy |
| TOPIC_LEAK_WORDS | empty | Optional guardrail eval words |

### Sessions, API, and limits

| Setting | Default | Meaning |
| --- | --- | --- |
| DB_PATH | data/benbot.sqlite | SQLite path |
| SESSION_IDLE_MINUTES | 60 | Idle time before a new session |
| SESSION_MAX_MESSAGES | 50 | Visitor messages per session |
| MESSAGE_MAX_CHARS | 1000 | Max message length over HTTP |
| MAX_CONCURRENT_TURNS | 2 | In-flight chat cap |
| DAILY_MESSAGE_CAP | 300 | UTC-day cap (0 disables) |
| BUSY_WAIT_SECONDS | 3 | Short wait when busy |
| API_HOST | 127.0.0.1 | Bind address for `python -m src.api` |
| API_PORT | 8000 | Port for local API |
| CORS_ALLOWED_ORIGINS | unset | Comma-separated origins; blank keeps CORS off |
| CONTACT_URL | unset | Optional contact link in copy |
| AI_LABEL | unset | Override AI label text |
| OPENING_MESSAGE | unset | Override opening message |
| LOGGING_NOTICE | unset | Override logging notice |
| FRAME_ANCESTORS | unset | Space-separated origins allowed to frame `/embed` |

### Logging and verification

| Setting | Default | Meaning |
| --- | --- | --- |
| LOG_LEVEL | WARNING | Python log level |
| LOG_TURNS | off | Log visitor turns when on |
| VERIFY_PRUNE_MIN_SENTENCES | 2 | Verification prune floor |

### Backup (production compose)

| Setting | Default | Meaning |
| --- | --- | --- |
| BACKUP_INTERVAL_MINUTES | 60 | Snapshot interval |
| SPACES_ENDPOINT | unset | S3-compatible endpoint |
| SPACES_BUCKET | unset | Bucket name |
| SPACES_PREFIX | unset | Key prefix |
| SPACES_KEY | unset | Access key |
| SPACES_SECRET | unset | Secret key |
| SPACES_REGION | us-east-1 | Region |
| SPACES_ADDRESSING_STYLE | auto | S3 addressing style |
| BACKUP_PING_URL | unset | Dead-man's-switch URL after upload |
| BACKUP_CONTENT | off | Daily content tarball when on |

Docker-specific vars (`BENBOT_HOME`, `BENBOT_IMAGE_PREFIX`, `BENBOT_TAG`, `PROXY_NETWORK`, `DEV_PROXY_API`) are documented in [`.env.example`](.env.example) and [`docs/web/containers.md`](docs/web/containers.md).

## Deployment

Production is **containers on a VPS**, images built in **private GitLab CI**, code public on GitHub — see [`docs/deploy/README.md`](docs/deploy/README.md). That runbook targets my setup (DigitalOcean droplet, Nginx Proxy Manager, Cloudflare). You would change hostnames, registry, and where the primary model runs.

## Privacy and safety (plain language)

- **Stored:** full visitor messages and replies, flags, retrieval metadata, and model connection used — in SQLite. **Not stored:** IP addresses or user agents ([`docs/decisions/018-sqlite-store.md`](docs/decisions/018-sqlite-store.md)).
- **Visible UI:** AI label, opening message, and a notice that chats are logged ([`docs/web/architecture.md`](docs/web/architecture.md) D17).
- **Third parties:** if you configure OpenRouter (or another hosted secondary), visitor text leaves your server for that provider.
- **Guards and verification** run in code; prompt rules are public by design. That helps transparency; it is **not** a legal or security guarantee.

## Tests

```bash
pytest
ruff check .
```

Integration: `RUN_INTEGRATION=1 pytest -m integration`. Dev-stack e2e: `./scripts/e2e.sh` (`RUN_E2E=1`). See [`docs/web/e2e.md`](docs/web/e2e.md).

## Public git

```bash
scripts/check_public_safe.sh
git config core.hooksPath .githooks   # optional pre-commit
```

## How this was built

Work is tracked in FeedPebble issues (BenBot project). Most code and docs were drafted with **coding agents**; I review behavior on real Ollama and Docker before calling something done. Eval scripts under `eval/` and decision records under `docs/decisions/` capture what we measured.

Article series: *placeholder — links will go here when published.*

## Docs index

Full map: [`docs/README.md`](docs/README.md).

## License

License: to be decided.
