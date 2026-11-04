# Backup and restore (SQLite → Spaces)

The `benbot_backup` container runs `python -m src.backup loop`: on each interval it
takes an **online** snapshot with Python’s `sqlite3.Connection.backup` (never a raw
copy of the live `.db`, `-wal`, or `-shm` files), runs `PRAGMA integrity_check` on
the snapshot, gzip-compresses it, and uploads to a **private** S3-compatible bucket
(DigitalOcean Spaces in production, MinIO in dev).

## Mount mode (WAL)

The backup container mounts `${BENBOT_HOME}/data` **read-only** at `/app/data`. The
snapshot opens the live file as `file:…?mode=ro`, which is enough for SQLite’s
backup API to read a consistent image while the API keeps writing. Temp files and
gzip output use `/tmp` (tmpfs). No `-shm` write is required on the data volume.

## Settings

See `.env.example` (`BACKUP_*`, `SPACES_*`). Secrets stay in `.env`; startup logs
use `Settings.masked_dict()` so keys are never printed in full.

| Variable | Default | Notes |
|----------|---------|--------|
| `BACKUP_INTERVAL_MINUTES` | 60 | Sleep between runs in `loop` |
| `SPACES_ENDPOINT` | — | e.g. `https://nyc3.digitaloceanspaces.com` |
| `SPACES_BUCKET` | — | Private bucket |
| `SPACES_PREFIX` | — | Object prefix, e.g. `benbot/prod` |
| `SPACES_KEY` / `SPACES_SECRET` | — | Prefer a bucket-scoped access key when Spaces allows |
| `SPACES_REGION` | `us-east-1` | Use the region slug (e.g. `nyc3`) for Spaces |
| `SPACES_ADDRESSING_STYLE` | `auto` | `path` for MinIO; `virtual` for Spaces |
| `BACKUP_PING_URL` | unset | HTTP GET only after a **successful** run |
| `BACKUP_CONTENT` | `off` | `on` adds a daily `content/` tar at midnight UTC |

Object layout:

- `…/hourly/benbot-YYYYMMDDTHHMMSSZ.db.gz` — every run
- `…/daily/benbot-YYYYMMDDTHHMMSSZ.db.gz` — extra copy when the run is at **00:xx UTC**
- `…/daily/content-YYYYMMDD.tar.gz` — optional when `BACKUP_CONTENT=on`

On failure the process logs the error, exits non-zero for a one-shot `run`, skips
the ping, and tries again on the next interval in `loop`.

## Retention (DigitalOcean Spaces)

Spaces supports **lifecycle rules** on a bucket (DigitalOcean control panel →
Spaces → bucket → **Settings** → **Lifecycle Rules**). Rules are prefix-based.

Suggested policy (adjust to taste):

1. Rule **1**: prefix `hourly/` (or `{SPACES_PREFIX}/hourly/`) → expire objects after **2 days** (48 hours).
2. Rule **2**: prefix `daily/` → expire after **30 days**.

Verify in the panel that rules are enabled; DO documents lifecycle under “Spaces
object lifecycle.” Bucket-scoped API keys are available in the control panel when
creating a Spaces access key limited to one bucket.

## List and restore

List keys:

```bash
docker compose run --rm backup list
```

Restore one object into a database path (default: `DB_PATH` from env):

```bash
docker compose run --rm backup restore 'dev/hourly/benbot-20261103T120000Z.db.gz' /app/data/benbot.sqlite
```

Or from the host via the helper script (uses the same compose service):

```bash
./scripts/restore_from_spaces.sh 'dev/hourly/benbot-20261103T120000Z.db.gz'
```

### Production restore checklist

1. List backups and pick an object key.
2. **Stop the API** so nothing writes to the database (`docker compose stop api`).
3. Run restore to `/app/data/benbot.sqlite` (same bind mount as the API).
4. Confirm stale `-wal` / `-shm` next to the db were removed (the restore command deletes them).
5. **Start the API** (`docker compose start api`).
6. Check `GET /api/health` and spot-check a session in the log UI or SQLite.

**Session deletion:** removing a session from the live database does **not** remove
it from snapshots already stored in Spaces (see `docs/decisions/018-sqlite-store.md`).

## Local dev (MinIO)

Dev compose adds `minio` (S3-compatible **pgsty/silo**; upstream MinIO CE images
are no longer pullable from Docker Hub / quay.io) and builds `backup` with MinIO
credentials. Create the
bucket once:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d minio
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm backup run
```

The first `run` may fail until the bucket exists; create `benbot-backups` in the
MinIO console at http://127.0.0.1:9001 or use the integration test helper.

## Implementation choice

- **Snapshot:** Python `sqlite3` backup API (stdlib, no extra binary).
- **Upload:** `boto3` S3 client with `signature_version=s3v4` (Spaces-compatible).
