# Content on the droplet

Ben copies private markdown to the server by hand and runs ingest by hand. Nothing in this repo fetches from a CMS or runs on a schedule.

## What gets searched

| File | Role |
|------|------|
| `content/about.md` | Prompt context only. Read on each chat turn. **Not** embedded or retrieved. |
| Every other `*.md` under `content/` | Searchable. Prose files split on headings; optional Q&A files use the `##` / `Q:` / `A:` format. |

Formats and samples live in `examples/` in the public repo.

## Copy files to the server

From your Mac (adjust host and path):

```bash
rsync -av content/ user@host:/opt/benbot/content/
```

The api and ingest containers run as a non-root user. Directories should be readable (`chmod -R a+rX content/` or group-readable mounts). Ingest only needs read access; the api mounts `content/` read-only.

Set `BENBOT_HOME` on the droplet to the directory that contains `content/` and `data/` (for example `/opt/benbot`).

## When to re-ingest

Run ingest after you add, edit, or remove any searchable markdown file (anything except `about.md`).

Editing `about.md` on the server takes effect on the next chat turn without re-ingest.

Until ingest finishes, the running API keeps serving the **previous** index. Edits on disk are invisible to search.

## Run ingest

On the host, ensure the data volume is writable by the api user (uid `10001`) and includes a temp directory for staging (compose sets `TMPDIR=/app/data/tmp` so index publish is not cross-device from tmpfs):

```bash
mkdir -p data/tmp
# chown as needed for your droplet (see Dockerfile uid 10001)
```

Production (embedder must be up):

```bash
cd /opt/benbot
docker compose --profile tools run --rm ingest
```

Validate parse only (no embedding calls):

```bash
docker compose --profile tools run --rm ingest --check
```

Force a full re-embed (model or prefix change):

```bash
docker compose --profile tools run --rm ingest --rebuild
```

Local dev uses `examples/` as content:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tools run --rm ingest
```

## Confirm retrieval

Inside the api container:

```bash
docker compose run --rm api python -m src.retrieve "your question"
```

Or use the chat UI after `scripts/dev-up.sh` / compose up.

## Index policy

**Always rebuild the index on the droplet.** Do not copy `data/index/` from your Mac. Vectors depend on the exact embedder and model that produced them. See `docs/decisions/023-index-portability.md`.
