"""SQLite sessions and the permanent exchange log.

The server owns conversation history. A client sends only a session id. The
row for a session is inserted on the first accepted message, so unused ids
never become empty sessions.

One short transaction inserts a turn as ``pending`` and commits. A second
transaction writes the final status after the model call. No transaction stays
open across ``answer_turn``.

``delete_session`` removes the session and its turns from this file. It does
not remove copies already written to backups.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

STATUSES = frozenset(
    {"pending", "ok", "session_full", "unavailable", "error", "interrupted"}
)
FINAL_STATUSES = frozenset({"ok", "unavailable", "error"})
PENDING_STALE = timedelta(minutes=3)
BUSY_TIMEOUT_MS = 5000
# WAL + NORMAL does not corrupt the file. A power loss can drop the last
# committed transaction. FULL would fsync every commit and adds no extra
# protection against corruption. See docs/decisions/018-sqlite-store.md.
SYNCHRONOUS = "NORMAL"
SESSION_ID_BYTES = 16

SCHEMA_V1 = (
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        last_active_at TEXT NOT NULL,
        message_count INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS turns (
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
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS turns_status_sequence
        ON turns (session_id, status, sequence)
    """,
)


@dataclass(frozen=True)
class Migration:
    """One step from ``user_version`` N-1 to N. Apply must be idempotent."""

    version: int
    rewrites_rows: bool
    apply: Callable[[sqlite3.Connection], None]


def _apply_v1(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_V1:
        conn.execute(statement)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, rewrites_rows=False, apply=_apply_v1),
)


@dataclass(frozen=True)
class SessionResolution:
    """What ``resolve_session`` decided. ``session_id`` is always a server id."""

    state: str
    session_id: str
    previous_session_id: str | None = None


@dataclass(frozen=True)
class TurnRecord:
    """One visitor turn as stored. ``reply`` is the text shown to the visitor."""

    session_id: str
    sequence: int
    created_at: str
    finished_at: str | None
    visitor_message: str
    reply: str
    status: str
    category: str | None = None
    flags: tuple[str, ...] = ()
    top_score: float | None = None
    retrieved: tuple[dict[str, Any], ...] = ()
    repair: str | None = None
    connection_used: str | None = None
    failover_active: bool | None = None
    models: dict[str, str] | None = None
    finish_reason: str | None = None
    timings: dict[str, int] | None = None
    prompt_tokens: int | None = None
    error: str | None = None


class Store:
    """Open the database, migrate it, and sweep stale pending turns."""

    def __init__(
        self,
        path: str | Path,
        *,
        idle_minutes: int = 60,
        max_messages: int = 50,
        clock: Callable[[], datetime] | None = None,
        busy_timeout_ms: int = BUSY_TIMEOUT_MS,
        migrations: Sequence[Migration] = MIGRATIONS,
    ) -> None:
        if idle_minutes < 0:
            raise ValueError("idle_minutes must be >= 0")
        if max_messages < 1:
            raise ValueError("max_messages must be >= 1")
        self.path = Path(path)
        self.idle = timedelta(minutes=idle_minutes)
        self.max_messages = max_messages
        self.clock = clock or _now
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        apply_migrations(self.path, migrations, busy_timeout_ms=busy_timeout_ms)
        self.sweep_pending()

    def create_session(self) -> str:
        """Mint a server id. The row is inserted by the first accepted message."""
        return secrets.token_hex(SESSION_ID_BYTES)

    def resolve_session(self, client_id: str | None) -> SessionResolution:
        """Map a client-supplied id to ok, expired, unknown, or full.

        An unknown or expired id yields a new server id. The client's string
        is never stored as the session id. The new row is not inserted here.
        """
        supplied = (client_id or "").strip()
        if not supplied:
            return SessionResolution(state="unknown", session_id=self.create_session())
        row = self._session_row(supplied)
        if row is None:
            return SessionResolution(state="unknown", session_id=self.create_session())
        last_active = _parse_utc(str(row["last_active_at"]))
        if self.clock() - last_active > self.idle:
            return SessionResolution(
                state="expired",
                session_id=self.create_session(),
                previous_session_id=str(row["id"]),
            )
        if int(row["message_count"]) >= self.max_messages:
            return SessionResolution(state="full", session_id=str(row["id"]))
        return SessionResolution(state="ok", session_id=str(row["id"]))

    def message_count(self, session_id: str) -> int:
        row = self._session_row(session_id)
        if row is None:
            return 0
        return int(row["message_count"])

    def messages_since_utc_midnight(self) -> int:
        """Visitor turns stored since 00:00 UTC today (persists across restarts)."""
        now = self.clock()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = _format_utc(start)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM turns WHERE created_at >= ?",
                (cutoff,),
            ).fetchone()
            return int(row["n"])
        finally:
            conn.close()

    def begin_turn(
        self,
        session_id: str,
        visitor_message: str,
        *,
        full_reply: str = "",
    ) -> TurnRecord:
        """Insert one turn and commit. Does not call the model.

        A new id creates the session. At the cap the turn is stored as
        ``session_full`` and the count does not grow. The cap counts visitor
        messages that were accepted (inserted as ``pending``).
        """
        if not session_id:
            raise ValueError("session_id is required")
        created = _format_utc(self.clock())
        with self._transaction() as conn:
            session = conn.execute(
                "SELECT message_count FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                sequence = 1
                conn.execute(
                    """
                    INSERT INTO sessions (id, created_at, last_active_at, message_count)
                    VALUES (?, ?, ?, 1)
                    """,
                    (session_id, created, created),
                )
                status = "pending"
                finished: str | None = None
                reply = ""
            elif int(session["message_count"]) >= self.max_messages:
                sequence = _next_sequence(conn, session_id)
                status = "session_full"
                finished = created
                reply = full_reply
                conn.execute(
                    "UPDATE sessions SET last_active_at = ? WHERE id = ?",
                    (created, session_id),
                )
            else:
                sequence = _next_sequence(conn, session_id)
                status = "pending"
                finished = None
                reply = ""
                conn.execute(
                    """
                    UPDATE sessions
                    SET message_count = message_count + 1, last_active_at = ?
                    WHERE id = ?
                    """,
                    (created, session_id),
                )
            conn.execute(
                """
                INSERT INTO turns (
                    session_id, sequence, created_at, finished_at,
                    visitor_message, reply, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, sequence, created, finished, visitor_message, reply, status),
            )
        stored = self.get_turn(session_id, sequence)
        if stored is None:
            raise RuntimeError("turn insert did not persist")
        return stored

    def finish_turn(
        self,
        session_id: str,
        sequence: int,
        *,
        reply: str,
        status: str = "ok",
        category: str | None = None,
        flags: Sequence[str] = (),
        top_score: float | None = None,
        retrieved: Sequence[Mapping[str, Any]] = (),
        repair: str | None = None,
        connection_used: str | None = None,
        failover_active: bool | None = None,
        models: Mapping[str, str] | None = None,
        finish_reason: str | None = None,
        timings: Mapping[str, int] | None = None,
        prompt_tokens: int | None = None,
        error: str | None = None,
    ) -> TurnRecord:
        """Commit the reply exactly as shown. The turn must still be pending."""
        if status not in FINAL_STATUSES:
            raise ValueError(f"status must be one of {sorted(FINAL_STATUSES)}")
        finished = _format_utc(self.clock())
        flag_json = json.dumps(list(flags))
        retrieved_json = json.dumps([dict(item) for item in retrieved])
        models_json = json.dumps(dict(models)) if models is not None else None
        timings_json = json.dumps(dict(timings)) if timings is not None else None
        failover = None if failover_active is None else int(bool(failover_active))
        with self._transaction() as conn:
            current = conn.execute(
                """
                SELECT status FROM turns
                WHERE session_id = ? AND sequence = ?
                """,
                (session_id, sequence),
            ).fetchone()
            if current is None:
                raise ValueError(f"no turn {session_id}#{sequence}")
            if str(current["status"]) != "pending":
                raise ValueError(f"turn {session_id}#{sequence} is {current['status']}")
            conn.execute(
                """
                UPDATE turns SET
                    finished_at = ?, reply = ?, status = ?, category = ?, flags = ?,
                    top_score = ?, retrieved = ?, repair = ?, connection_used = ?,
                    failover_active = ?, models = ?, finish_reason = ?,
                    timings = ?, prompt_tokens = ?, error = ?
                WHERE session_id = ? AND sequence = ?
                """,
                (
                    finished,
                    reply,
                    status,
                    category,
                    flag_json,
                    top_score,
                    retrieved_json,
                    repair,
                    connection_used,
                    failover,
                    models_json,
                    finish_reason,
                    timings_json,
                    prompt_tokens,
                    error,
                    session_id,
                    sequence,
                ),
            )
            conn.execute(
                "UPDATE sessions SET last_active_at = ? WHERE id = ?",
                (finished, session_id),
            )
        stored = self.get_turn(session_id, sequence)
        if stored is None or stored.reply != reply or stored.status != status:
            raise RuntimeError("finished turn did not persist")
        return stored

    def history(self, session_id: str, turns: int) -> list[dict[str, str]]:
        """Last N ``ok`` turns, oldest first, as user/assistant messages.

        Any other status is left out of the prompt.
        """
        if turns < 0:
            raise ValueError("turns must be >= 0")
        if turns == 0:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT visitor_message, reply FROM turns
                WHERE session_id = ? AND status = 'ok'
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (session_id, turns),
            ).fetchall()
        finally:
            conn.close()
        messages: list[dict[str, str]] = []
        for row in reversed(rows):
            messages.append({"role": "user", "content": str(row["visitor_message"])})
            messages.append({"role": "assistant", "content": str(row["reply"])})
        return messages

    def delete_session(self, session_id: str) -> bool:
        """Remove this session and its turns from this database file.

        Copies already stored in backups are not affected.
        """
        with self._transaction() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cursor.rowcount > 0

    def sweep_pending(self, older_than: timedelta = PENDING_STALE) -> int:
        """Mark pending turns older than ``older_than`` as ``interrupted``."""
        cutoff = _format_utc(self.clock() - older_than)
        finished = _format_utc(self.clock())
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE turns
                SET status = 'interrupted', finished_at = ?, error = ?
                WHERE status = 'pending' AND created_at < ?
                """,
                (finished, "pending turn was still open at startup", cutoff),
            )
            return cursor.rowcount

    def get_turn(self, session_id: str, sequence: int) -> TurnRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM turns
                WHERE session_id = ? AND sequence = ?
                """,
                (session_id, sequence),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return _turn_from_row(row)

    def _session_row(self, session_id: str) -> sqlite3.Row | None:
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        """A new connection for this thread. Do not share it across threads."""
        conn = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=True,
        )
        conn.row_factory = sqlite3.Row
        apply_pragmas(conn, self.busy_timeout_ms)
        return conn

    def _transaction(self) -> _Transaction:
        return _Transaction(self._connect())


class _Transaction:
    """BEGIN IMMEDIATE and commit. The connection closes either way."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            if exc_type is None:
                self.conn.execute("COMMIT")
            else:
                self.conn.execute("ROLLBACK")
        finally:
            self.conn.close()


def apply_pragmas(conn: sqlite3.Connection, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute(f"PRAGMA synchronous={SYNCHRONOUS}")


def apply_migrations(
    path: Path,
    migrations: Sequence[Migration],
    *,
    busy_timeout_ms: int = BUSY_TIMEOUT_MS,
) -> None:
    """Move ``user_version`` forward. A row-rewriting step copies the file first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        apply_pragmas(conn, busy_timeout_ms)
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        for migration in migrations:
            if migration.version <= current:
                continue
            if migration.version != current + 1:
                raise RuntimeError(
                    f"migration {migration.version} skips {current}"
                )
            if migration.rewrites_rows and _has_user_rows(conn):
                conn.close()
                snapshot_database(path, migration.version)
                conn = sqlite3.connect(path, isolation_level=None)
                apply_pragmas(conn, busy_timeout_ms)
            conn.execute("BEGIN IMMEDIATE")
            try:
                migration.apply(conn)
                conn.execute(f"PRAGMA user_version = {int(migration.version)}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            current = migration.version
    finally:
        conn.close()


def snapshot_database(path: Path, version: int) -> Path:
    """Consistent sibling copy via the backup API, not a raw copy of the WAL."""
    stamp = _format_utc(_now()).replace(":", "").replace("-", "")
    dest = path.with_name(f"{path.name}.before-v{version}-{stamp}")
    source = sqlite3.connect(path, isolation_level=None)
    try:
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return dest


def _has_user_rows(conn: sqlite3.Connection) -> bool:
    tables = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    for table in tables:
        name = str(table[0])
        row = conn.execute(f"SELECT 1 FROM {quote_ident(name)} LIMIT 1").fetchone()
        if row is not None:
            return True
    return False


def quote_ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"unsafe table name {name!r}")
    return '"' + name + '"'


def _next_sequence(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM turns WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["next_seq"])


def _turn_from_row(row: sqlite3.Row) -> TurnRecord:
    flags = json.loads(row["flags"]) if row["flags"] else []
    retrieved = json.loads(row["retrieved"]) if row["retrieved"] else []
    models = json.loads(row["models"]) if row["models"] else None
    timings = json.loads(row["timings"]) if row["timings"] else None
    failover = row["failover_active"]
    return TurnRecord(
        session_id=str(row["session_id"]),
        sequence=int(row["sequence"]),
        created_at=str(row["created_at"]),
        finished_at=None if row["finished_at"] is None else str(row["finished_at"]),
        visitor_message=str(row["visitor_message"]),
        reply=str(row["reply"]),
        status=str(row["status"]),
        category=None if row["category"] is None else str(row["category"]),
        flags=tuple(str(flag) for flag in flags),
        top_score=None if row["top_score"] is None else float(row["top_score"]),
        retrieved=tuple(retrieved),
        repair=None if row["repair"] is None else str(row["repair"]),
        connection_used=(
            None if row["connection_used"] is None else str(row["connection_used"])
        ),
        failover_active=None if failover is None else bool(failover),
        models=None if models is None else {str(k): str(v) for k, v in models.items()},
        finish_reason=None if row["finish_reason"] is None else str(row["finish_reason"]),
        timings=None if timings is None else {str(k): int(v) for k, v in timings.items()},
        prompt_tokens=None if row["prompt_tokens"] is None else int(row["prompt_tokens"]),
        error=None if row["error"] is None else str(row["error"]),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
