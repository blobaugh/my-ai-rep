"""CLI to inspect and occasionally delete sessions in the conversation log."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import load_settings
from src.review.db import (
    fetch_turns,
    open_readonly,
    session_ids_with_prefix,
    turns_for_session,
)
from src.review.format import (
    export_turns_csv,
    export_turns_md,
    format_gap_group,
    format_stats,
    format_turn,
    write_export,
)
from src.review.queries import (
    GUARD_CATEGORIES,
    compute_stats,
    failover_turns,
    gap_groups,
    parse_since,
)
from src.store import Store


def _db_path() -> Path:
    settings = load_settings()
    path = Path(settings.db_path)
    if not path.is_absolute():
        root = Path(__file__).resolve().parents[2]
        path = root / path
    return path


def _maybe_export(turns, args) -> None:
    if not getattr(args, "out", None):
        return
    fmt = getattr(args, "format", None) or "md"
    body = export_turns_csv(turns) if fmt == "csv" else export_turns_md(
        turns, short=getattr(args, "short", False)
    )
    write_export(Path(args.out), body)
    print(f"wrote {args.out}")


def _add_export_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--format", choices=("md", "csv"), default="md")
    parser.add_argument("--out", help="Export path for md/csv")


def cmd_gaps(args: argparse.Namespace) -> int:
    since = parse_since(args.since) if args.since else None
    with open_readonly(_db_path()) as conn:
        groups = gap_groups(
            conn,
            since=since,
            limit=args.limit,
            min_count=args.min_count,
        )
    for group in groups:
        print(format_gap_group(group))
    if args.out:
        turns = [turn for group in groups for turn in group.turns]
        _maybe_export(turns, args)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    since = parse_since(args.since) if args.since else None
    with open_readonly(_db_path()) as conn:
        turns = fetch_turns(
            conn,
            category=getattr(args, "category", None),
            flag=getattr(args, "flag", None),
            status=getattr(args, "status", None),
            since=since,
        )
    if args.limit is not None:
        turns = turns[: args.limit]
    for turn in turns:
        print(format_turn(turn, short=args.short))
        print()
    _maybe_export(turns, args)
    return 0


def cmd_offtopic(args: argparse.Namespace) -> int:
    args.category = "off_topic"
    args.flag = None
    return cmd_list(args)


def cmd_suspect(args: argparse.Namespace) -> int:
    since = parse_since(args.since) if args.since else None
    with open_readonly(_db_path()) as conn:
        guard = fetch_turns(
            conn, since=since, status="ok", categories=tuple(GUARD_CATEGORIES)
        )
        injected = fetch_turns(conn, since=since, status="ok", flag="injection_suspect")
    seen: set[tuple[str, int]] = set()
    turns = []
    for turn in guard + injected:
        key = (turn.session_id, turn.sequence)
        if key in seen:
            continue
        seen.add(key)
        turns.append(turn)
    turns.sort(key=lambda row: row.created_at, reverse=True)
    if args.limit is not None:
        turns = turns[: args.limit]
    for turn in turns:
        print(format_turn(turn, short=args.short))
        print()
    _maybe_export(turns, args)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    with open_readonly(_db_path()) as conn:
        matches = session_ids_with_prefix(conn, args.session_id)
        if not matches:
            print("error: no session matches that id", file=sys.stderr)
            return 1
        if len(matches) > 1:
            print("error: id prefix is ambiguous:", ", ".join(matches), file=sys.stderr)
            return 1
        session_id = matches[0]
        turns = turns_for_session(conn, session_id)
    print(f"session {session_id} ({len(turns)} turns)")
    for turn in turns:
        print(format_turn(turn, short=args.short))
        print()
    return 0


def cmd_failovers(args: argparse.Namespace) -> int:
    since = parse_since(args.since) if args.since else None
    with open_readonly(_db_path()) as conn:
        turns = failover_turns(conn, since=since)
    if args.limit is not None:
        turns = turns[: args.limit]
    print(f"{len(turns)} failover turn(s)")
    for turn in turns:
        print(format_turn(turn, short=args.short))
        print()
    _maybe_export(turns, args)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    since = parse_since(args.since) if args.since else None
    with open_readonly(_db_path()) as conn:
        stats = compute_stats(conn, since=since)
    print(format_stats(stats))
    return 0


def cmd_delete_session(args: argparse.Namespace) -> int:
    path = _db_path()
    with open_readonly(path) as conn:
        matches = session_ids_with_prefix(conn, args.session_id)
        if not matches:
            print("error: no session matches that id", file=sys.stderr)
            return 1
        if len(matches) > 1:
            print("error: id prefix is ambiguous", file=sys.stderr)
            return 1
        session_id = matches[0]
        turns = turns_for_session(conn, session_id)
    print(f"session {session_id} — {len(turns)} turn(s)")
    for turn in turns:
        preview = turn.visitor_message
        if len(preview) > 60:
            preview = preview[:60] + "…"
        print(f"  #{turn.sequence} {turn.created_at}: {preview!r}")
    if not args.yes:
        answer = input("Delete this session from the live database? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("cancelled")
            return 0
    store = Store(path)
    if not store.delete_session(session_id):
        print("error: delete failed", file=sys.stderr)
        return 1
    print("deleted.")
    print(
        "Reminder: existing backup snapshots in Spaces may still contain this session."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review chat conversation logs")
    sub = parser.add_subparsers(dest="command", required=True)

    gaps = sub.add_parser("gaps", help="Grouped content gaps and weak answers")
    gaps.add_argument("--since")
    gaps.add_argument("--limit", type=int)
    gaps.add_argument("--min-count", type=int, default=1)
    _add_export_flags(gaps)
    gaps.set_defaults(func=cmd_gaps)

    list_p = sub.add_parser("list", help="List turns with filters")
    list_p.add_argument("--category")
    list_p.add_argument("--flag")
    list_p.add_argument("--status")
    list_p.add_argument("--since")
    list_p.add_argument("--limit", type=int)
    _add_export_flags(list_p)
    list_p.set_defaults(func=cmd_list)

    for name, help_text in (
        ("offtopic", "Off-topic turns"),
        ("suspect", "Injection suspects and guard hits"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--since")
        cmd.add_argument("--limit", type=int)
        _add_export_flags(cmd)
        cmd.set_defaults(func=cmd_offtopic if name == "offtopic" else cmd_suspect)

    show = sub.add_parser("show", help="Full session transcript")
    show.add_argument("session_id")
    show.add_argument("--short", action="store_true")
    show.set_defaults(func=cmd_show)

    fail = sub.add_parser("failovers", help="Turns served on secondary connection")
    fail.add_argument("--since")
    fail.add_argument("--limit", type=int)
    _add_export_flags(fail)
    fail.set_defaults(func=cmd_failovers)

    stats = sub.add_parser("stats", help="Aggregate rates and timings")
    stats.add_argument("--since")
    stats.set_defaults(func=cmd_stats)

    delete = sub.add_parser("delete-session", help="Remove one session from SQLite")
    delete.add_argument("session_id")
    delete.add_argument("--yes", action="store_true")
    delete.set_defaults(func=cmd_delete_session)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
