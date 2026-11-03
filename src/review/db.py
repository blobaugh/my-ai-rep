"""Read-only database access for review commands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.store import TurnRecord, _turn_from_row


def open_readonly(path: str | Path) -> sqlite3.Connection:
    """Open WAL database read-only (safe alongside a running API writer)."""
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"database not found: {resolved}")
    uri = f"file:{resolved}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_turns(
    conn: sqlite3.Connection,
    *,
    category: str | None = None,
    flag: str | None = None,
    status: str | None = None,
    since: str | None = None,
    categories: tuple[str, ...] | None = None,
    any_flag: str | None = None,
) -> list[TurnRecord]:
    clauses: list[str] = []
    params: list[object] = []
    if category:
        clauses.append("category = ?")
        params.append(category)
    if categories:
        placeholders = ",".join("?" for _ in categories)
        clauses.append(f"category IN ({placeholders})")
        params.extend(categories)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if since:
        clauses.append("created_at >= ?")
        params.append(since if "T" in since else f"{since}T00:00:00Z")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM turns {where} ORDER BY created_at DESC",
        params,
    ).fetchall()
    turns = [_turn_from_row(row) for row in rows]
    if flag:
        turns = [turn for turn in turns if flag in turn.flags]
    if any_flag:
        turns = [turn for turn in turns if any_flag in turn.flags]
    return turns


def session_ids_with_prefix(conn: sqlite3.Connection, prefix: str) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM sessions WHERE id LIKE ? ORDER BY id",
        (prefix + "%",),
    ).fetchall()
    return [str(row["id"]) for row in rows]


def turns_for_session(conn: sqlite3.Connection, session_id: str) -> list[TurnRecord]:
    rows = conn.execute(
        """
        SELECT * FROM turns WHERE session_id = ?
        ORDER BY sequence ASC
        """,
        (session_id,),
    ).fetchall()
    return [_turn_from_row(row) for row in rows]


def flags_contain(row_flags: str | None, name: str) -> bool:
    if not row_flags:
        return False
    try:
        parsed = json.loads(row_flags)
    except json.JSONDecodeError:
        return False
    return name in parsed
