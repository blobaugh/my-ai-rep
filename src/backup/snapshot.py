"""Online SQLite backup without copying -wal or -shm directly."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def integrity_ok(path: Path) -> bool:
    conn = sqlite3.connect(path, timeout=30)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    return row is not None and str(row[0]).lower() == "ok"


def snapshot_database(source: Path, destination: Path) -> None:
    """Copy a consistent database image using SQLite's backup API."""
    if not source.is_file():
        raise FileNotFoundError(f"database not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        destination.unlink()
    source_uri = f"file:{source.resolve()}?mode=ro"
    src = sqlite3.connect(source_uri, uri=True, timeout=30)
    dst = sqlite3.connect(destination, timeout=30)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    if not integrity_ok(destination):
        raise RuntimeError(f"integrity_check failed on snapshot {destination}")
