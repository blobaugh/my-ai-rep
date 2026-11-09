# Review workflow (CLI)

BenBot logs every exchange in SQLite. The review tool reads that log **read-only**
(while the API is running) so Ben can find gaps, weak answers, and abuse attempts
without exposing an admin web UI.

Run inside the api image:

```bash
# Droplet / git checkout (built images): same compose merge as checkout-up.sh.
# --no-deps avoids starting embedder; review only reads SQLite on the data mount.
docker compose -f docker-compose.yml -f docker-compose.checkout.yml run --rm --no-deps api \
  python -m src.review gaps
```

Production (pre-pulled registry images, no checkout overlay):

```bash
docker compose run --rm --no-deps api python -m src.review gaps
```

Locally:

```bash
python -m src.review gaps
```

## Typical loop

1. **`gaps`** — grouped `no_answer` questions plus turns flagged
   `weak_retrieval` or `repair_fallback`. Newest groups first.
2. Pick a repeated question. **`show <session-id>`** (or an id prefix) for full
   context: retrieval scores, flags, repair mode, connection, timings.
3. Fix content under `content/` (a prose markdown file or an optional Q&A entry
   with `##` id, `Q:` / `A:`, `source:`, `review:` — see BENBOT-36).
4. Rebuild the index: `docker compose --profile tools run --rm ingest` (BENBOT-25).
5. Ask the same question again in chat and confirm the category moves to
   `answered`.

## Other commands

| Command | Purpose |
|---------|---------|
| `list` | Filter by `--category`, `--flag`, `--status`, `--since` |
| `offtopic` | `off_topic` category |
| `suspect` | `injection_suspect` flag and guard categories |
| `failovers` | Turns that used the secondary LLM connection |
| `stats` | Daily category counts, answer rates, timing percentiles |
| `delete-session <id>` | Remove one session (prompts unless `--yes`) |

Add `--out FILE` and `--format md|csv` on list-style commands to export.

## Example

```text
$ python -m src.review gaps --limit 3
[2x] What is your favorite board game?
  normalized: what is your favorite board game
  first: 2026-11-01T18:02:11Z  last: 2026-11-03T09:14:02Z

$ python -m src.review show a1b2c3d4
session a1b2c3d4e5… (1 turns)
--- 2026-11-03T09:14:02Z session a1b2c3d4 #1 ---
category: no_answer  flags: weak_retrieval
…
```

## Clustering (future)

Similar-but-not-identical gap questions could be grouped with embeddings and a
cosine threshold. That is not implemented yet; use normalized text grouping in
`gaps` for now.

## Deletion vs backups

`delete-session` removes the session from the **live** database only. Hourly
Spaces snapshots still contain deleted sessions until they expire. See
`docs/deploy/backup-restore.md`.
