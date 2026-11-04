# Operations

Day-two tasks on the droplet (`BENBOT_HOME`, usually `/opt/benbot`).

## Update images

After CI pushes new tags:

```bash
cd /opt/benbot
docker compose pull
docker compose up -d
```

Watch health:

```bash
docker compose ps
docker compose logs --tail=50 api web embedder backup
```

The api healthcheck allows a **start-period** (~40s) before marking unhealthy; embedder
can take **several minutes** when the model volume is cold. Do not restart in a loop.

**When to re-ingest:** after deploy only if embedding model, ingest code, or content
processing changed — not for every image bump. Content edits always need ingest
([content.md](./content.md)).

## Rollback

Pin the previous known-good tag in `.env`:

```bash
BENBOT_TAG=abc1234   # CI short SHA or vX.Y.Z
docker compose pull
docker compose up -d
```

Database and index on disk survive rollback; schema migrations are forward-only
(see below).

## Database migrations

SQLite migrations run at api startup. The store **copies the DB file before migrating**
(BENBOT-20). If migration fails, the previous file remains.

Restore from backup if data is corrupt: [backup-restore.md](./backup-restore.md).

## Re-ingest (full index rebuild)

Required when:

- Searchable markdown under `content/` changed
- `EMBED_MODEL` or embed prefixes changed
- Index format changed in a release note

```bash
docker compose --profile tools run --rm ingest
```

Until ingest completes, the API serves the **previous** index.

## Logs

```bash
docker compose logs --tail=200 api
docker compose logs -f web
```

Turn up verbosity temporarily in `.env`: `LOG_LEVEL=INFO`, `LOG_TURNS=on` (remember to
revert — visitor text may appear in logs).

## Disk usage

```bash
du -sh data/ content/
docker system df
```

**Prune cautions:** `docker system prune` can remove unused images you might roll back to.
Prune volumes only if you understand what is deleted — **never** prune `data/` or the
`ollama_models` volume without a backup.

## Rotate secrets

| Secret | Where |
| --- | --- |
| OpenRouter | `LLM_SECONDARY_API_KEY` in `.env`, restart api |
| Spaces | `SPACES_KEY` / `SPACES_SECRET`, restart backup |
| Registry | `docker login` credentials on droplet |

After `.env` edits: `docker compose up -d` (recreate containers that read env).

## Monitoring

- **Uptime:** HTTP GET on `https://bot.benlobaugh.com/api/health` every 1–5 minutes.
- **Backup dead-man's-switch:** configure `BACKUP_PING_URL` (BENBOT-26) so missed
  hourly uploads alert you.

## Limits and abuse

Production defaults (see `docs/web/limits.md`): concurrent turns, daily cap, busy response.
Tune via `MAX_CONCURRENT_TURNS`, `DAILY_MESSAGE_CAP`, `BUSY_WAIT_SECONDS` in `.env`.
