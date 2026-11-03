"""SQLite session store. No network."""

from __future__ import annotations

import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from src.store import (
    FINAL_STATUSES,
    MIGRATIONS,
    Migration,
    Store,
    apply_migrations,
)

FORBIDDEN_NAMES = frozenset(
    {
        "ip",
        "ip_address",
        "remote_addr",
        "user_agent",
        "useragent",
        "cookie",
        "cookies",
        "header",
        "headers",
    }
)


def _clock(start: datetime | None = None) -> tuple[dict[str, datetime], object]:
    state = {"now": start or datetime(2026, 1, 1, tzinfo=timezone.utc)}

    def current() -> datetime:
        return state["now"]

    return state, current


def test_migration_on_an_empty_file_and_an_old_version(tmp_path) -> None:
    fresh = tmp_path / "fresh.sqlite"
    Store(fresh, idle_minutes=60, max_messages=50)
    assert _user_version(fresh) == 1
    store2 = Store(fresh)
    assert store2.path == fresh
    assert _user_version(fresh) == 1

    old = tmp_path / "old.sqlite"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE legacy (note TEXT)")
    conn.execute("INSERT INTO legacy (note) VALUES ('keep')")
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    apply_migrations(old, MIGRATIONS)
    assert _user_version(old) == 1
    conn = sqlite3.connect(old)
    assert conn.execute("SELECT note FROM legacy").fetchone()[0] == "keep"
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    conn.close()
    assert "sessions" in tables
    assert "turns" in tables


def test_row_rewriting_migration_copies_the_file_first(tmp_path) -> None:
    path = tmp_path / "log.sqlite"
    clock, current = _clock()
    store = Store(path, clock=current, max_messages=10)
    session_id = store.create_session()
    store.begin_turn(session_id, "before")

    def rewrite(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE sessions SET message_count = message_count + 5")

    apply_migrations(
        path,
        (
            *MIGRATIONS,
            Migration(version=2, rewrites_rows=True, apply=rewrite),
        ),
    )
    copies = list(tmp_path.glob("log.sqlite.before-v2-*"))
    assert len(copies) == 1
    saved = sqlite3.connect(copies[0])
    assert saved.execute("SELECT message_count FROM sessions").fetchone()[0] == 1
    saved.close()
    live = sqlite3.connect(path)
    assert live.execute("SELECT message_count FROM sessions").fetchone()[0] == 6
    assert live.execute("PRAGMA user_version").fetchone()[0] == 2
    live.close()
    assert clock["now"]


def test_schema_and_signatures_have_no_identifying_fields(tmp_path) -> None:
    path = tmp_path / "s.sqlite"
    Store(path)
    conn = sqlite3.connect(path)
    columns: set[str] = set()
    try:
        for table in ("sessions", "turns"):
            for row in conn.execute(f"PRAGMA table_info({table})"):
                columns.add(str(row[1]).lower())
    finally:
        conn.close()
    assert columns.isdisjoint(FORBIDDEN_NAMES)
    for name, obj in inspect.getmembers(Store, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        params = set(inspect.signature(obj).parameters)
        assert params.isdisjoint(FORBIDDEN_NAMES)


def test_unknown_expired_and_full_sessions(tmp_path) -> None:
    clock, current = _clock()
    store = Store(tmp_path / "s.sqlite", clock=current, idle_minutes=60, max_messages=2)
    minted = store.create_session()
    assert len(minted) == 32
    assert _session_count(store) == 0

    unknown = store.resolve_session("client-picked-id")
    assert unknown.state == "unknown"
    assert unknown.session_id != "client-picked-id"
    assert _session_count(store) == 0

    first = store.begin_turn(unknown.session_id, "Hello")
    assert first.status == "pending"
    assert first.visitor_message == "Hello"
    assert _session_count(store) == 1
    store.finish_turn(first.session_id, first.sequence, reply="Hi")
    active = store.resolve_session(unknown.session_id)
    assert active.state == "ok"
    assert active.session_id == unknown.session_id

    clock["now"] = clock["now"] + timedelta(minutes=60)
    still = store.resolve_session(unknown.session_id)
    assert still.state == "ok"
    clock["now"] = clock["now"] + timedelta(seconds=1)
    expired = store.resolve_session(unknown.session_id)
    assert expired.state == "expired"
    assert expired.session_id != unknown.session_id
    assert expired.previous_session_id == unknown.session_id
    assert _session_count(store) == 1

    other = store.create_session()
    store.finish_turn(
        store.begin_turn(other, "one").session_id,
        1,
        reply="a",
    )
    store.finish_turn(
        store.begin_turn(other, "two").session_id,
        2,
        reply="b",
    )
    assert store.resolve_session(other).state == "full"
    rejected = store.begin_turn(other, "three")
    assert rejected.status == "session_full"
    assert _message_count(store, other) == 2


def test_history_window_excludes_non_ok_and_delete_removes_turns(tmp_path) -> None:
    store = Store(tmp_path / "s.sqlite", max_messages=10)
    session_id = store.create_session()
    for text, reply, status in (
        ("one", "A", "ok"),
        ("two", "B", "error"),
        ("three", "C", "ok"),
        ("four", "D", "unavailable"),
        ("five", "E", "ok"),
    ):
        begun = store.begin_turn(session_id, text)
        store.finish_turn(
            session_id, begun.sequence, reply=reply, status=status
        )
    history = store.history(session_id, 2)
    assert history == [
        {"role": "user", "content": "three"},
        {"role": "assistant", "content": "C"},
        {"role": "user", "content": "five"},
        {"role": "assistant", "content": "E"},
    ]
    assert store.history(session_id, 0) == []
    stored = store.get_turn(session_id, 1)
    assert stored is not None
    assert stored.reply == "A"
    assert store.delete_session(session_id) is True
    assert store.history(session_id, 6) == []
    assert store.get_turn(session_id, 1) is None
    assert store.delete_session(session_id) is False


def test_pending_sweep_marks_old_rows_interrupted(tmp_path) -> None:
    clock, current = _clock()
    path = tmp_path / "s.sqlite"
    store = Store(path, clock=current)
    session_id = store.create_session()
    pending = store.begin_turn(session_id, "still working")
    assert pending.status == "pending"
    clock["now"] = clock["now"] + timedelta(minutes=2)
    assert store.sweep_pending() == 0
    clock["now"] = clock["now"] + timedelta(minutes=2)
    assert store.sweep_pending() == 1
    interrupted = store.get_turn(session_id, pending.sequence)
    assert interrupted is not None
    assert interrupted.status == "interrupted"
    assert interrupted.error
    reopened = Store(path, clock=current)
    assert reopened.get_turn(session_id, pending.sequence).status == "interrupted"


def test_reply_is_stored_exactly_as_finished(tmp_path) -> None:
    store = Store(tmp_path / "s.sqlite")
    session_id = store.create_session()
    begun = store.begin_turn(session_id, "  as typed  ")
    reply = "Line one.\nLine two."
    finished = store.finish_turn(
        session_id,
        begun.sequence,
        reply=reply,
        status="ok",
        category="answered",
        flags=("repair_prune",),
        top_score=0.5,
        retrieved=({"id": "qa#intro", "score": 0.5},),
        repair="prune",
        connection_used="primary",
        failover_active=False,
        models={"chat": "local", "embed": "embed"},
        finish_reason="stop",
        timings={"embed": 1, "search": 2, "model": 3, "total": 6},
        prompt_tokens=12,
    )
    assert finished.reply == reply
    again = store.get_turn(session_id, begun.sequence)
    assert again is not None
    assert again.reply == reply
    assert again.visitor_message == "  as typed  "
    assert again.flags == ("repair_prune",)
    assert again.category == "answered"
    assert again.top_score == 0.5
    assert again.retrieved[0]["id"] == "qa#intro"
    assert again.failover_active is False
    assert again.models == {"chat": "local", "embed": "embed"}
    assert again.prompt_tokens == 12
    with pytest.raises(ValueError):
        store.finish_turn(session_id, begun.sequence, reply="nope")


def test_acceptance_threads_expiry_cap_and_sweep(tmp_path) -> None:
    """3 sessions, 50 turns from 8 threads, one expiry, one cap, one sweep."""
    clock, current = _clock()
    path = tmp_path / "accept.sqlite"
    store = Store(path, clock=current, idle_minutes=60, max_messages=50)
    capped = store.create_session()
    expiring = store.create_session()
    pending_session = store.create_session()

    errors: list[BaseException] = []

    def write_one(index: int) -> None:
        try:
            begun = store.begin_turn(capped, f"message {index}")
            if begun.status == "pending":
                store.finish_turn(capped, begun.sequence, reply=f"reply {index}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write_one, range(50)))
    assert errors == []
    assert _message_count(store, capped) == 50
    assert store.resolve_session(capped).state == "full"
    overflow = store.begin_turn(capped, "one more")
    assert overflow.status == "session_full"

    store.finish_turn(
        store.begin_turn(expiring, "earlier").session_id,
        1,
        reply="then",
    )
    clock["now"] = clock["now"] + timedelta(minutes=61)
    expired = store.resolve_session(expiring)
    assert expired.state == "expired"
    assert expired.session_id != expiring

    begun = store.begin_turn(pending_session, "left open")
    assert begun.status == "pending"
    clock["now"] = clock["now"] + timedelta(minutes=4)
    assert store.sweep_pending() == 1
    assert store.get_turn(pending_session, begun.sequence).status == "interrupted"
    assert set(FINAL_STATUSES) == {"ok", "unavailable", "error"}


def _user_version(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def _session_count(store: Store) -> int:
    conn = sqlite3.connect(store.path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
    finally:
        conn.close()


def _message_count(store: Store, session_id: str) -> int:
    conn = sqlite3.connect(store.path)
    try:
        row = conn.execute(
            "SELECT message_count FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row[0])
