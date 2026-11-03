# SQLite for sessions and the exchange log

**Status:** Accepted
**Date:** 2026-11-03
**Issue:** BENBOT-20

## Decision

One SQLite file (`DB_PATH`, default `data/benbot.sqlite`) holds sessions and every visitor turn. The standard library `sqlite3` module is the whole data layer. There is no ORM.

The server issues the session id (`secrets.token_hex(16)`, 128 bits). The browser will store only that id. A client-supplied unknown id never becomes the stored id. The session row is inserted on the first accepted message, so an id that is only resolved and never used does not leave an empty session.

History for the prompt is the last `HISTORY_TURNS` turns whose status is `ok`, as user and assistant messages. Every other status stays in the log and stays out of the prompt.

## Why SQLite

One API process, one writer, and a log that has to survive restarts. A single file on the data volume is enough. Postgres would add a service this scale does not need. Revisit this when more than one API process writes, or when the file is large enough that backups and queries get in the way.

## Why WAL

`journal_mode=WAL` lets a reader run while one writer commits. The web process will read history and write the log on different requests. Rollback-journal mode blocks readers for the whole write.

`synchronous=NORMAL` is the WAL setting SQLite documents as safe from corruption. A power loss can drop the most recently committed transaction. It cannot tear the file. `FULL` would fsync every commit and would not make corruption less likely. `busy_timeout` is 5 seconds so a waiting writer retries instead of failing with "database is locked". `foreign_keys=ON`.

Each call opens its own connection and closes it. SQLite forbids sharing a connection across threads unless that check is turned off. This store leaves the check on. A transaction is `BEGIN IMMEDIATE` around one insert or one update, then commit. The model call happens between those two transactions, never inside one.

## Retention and identity

Ben decided the log is kept indefinitely, and that it stores no IP address, user agent, header, cookie, or any identifier other than the random session id. Visitor text is stored as typed. The reply is stored as the text shown to the visitor.

`delete_session` removes that session and its turns from this file. It does not remove copies already written to backups.

`SESSION_MAX_MESSAGES` (default 50) counts visitor messages accepted into the session (inserted as `pending`). A later message on that session is stored as `session_full` and does not increment the count. There is no compaction.

`SESSION_IDLE_MINUTES` (default 60) is how long after the last accepted message the id is still the same session. Longer than that, the next resolve mints a new id and leaves the old rows in place.

A `pending` turn still open after 3 minutes is marked `interrupted` when the store opens and when `sweep_pending` runs. That covers a process death during the model call.

## Migrations

`PRAGMA user_version` starts at 0. Each migration is one version step and must be safe to run again. Before a migration that changes existing rows, the store writes a consistent sibling copy with the backup API (`name.before-vN-<timestamp>`). That copy is not a raw copy of the `-wal` or `-shm` file. Version 1 only creates tables, so it does not take a copy.

## Schema

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    message_count INTEGER NOT NULL
);

CREATE TABLE turns (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    visitor_message TEXT NOT NULL,
    reply TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    category TEXT,
    flags TEXT,
    top_score REAL,
    retrieved TEXT,
    repair TEXT,
    connection_used TEXT,
    failover_active INTEGER,
    models TEXT,
    finish_reason TEXT,
    timings TEXT,
    prompt_tokens INTEGER,
    error TEXT,
    PRIMARY KEY (session_id, sequence)
);
```

`flags`, `retrieved`, `models`, and `timings` are JSON text. `status` is `pending`, `ok`, `session_full`, `unavailable`, `error`, or `interrupted`. Timestamps are UTC `YYYY-MM-DDTHH:MM:SSZ`.
