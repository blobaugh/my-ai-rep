"""Terminal-friendly formatters."""

from __future__ import annotations

import csv
import textwrap
from io import StringIO
from pathlib import Path

from src.review.queries import GapGroup, SummaryStats
from src.store import TurnRecord

WRAP = 78


def _short_session(session_id: str) -> str:
    return session_id[:8]


def _retrieved_summary(turn: TurnRecord, limit: int = 3) -> str:
    parts: list[str] = []
    for item in turn.retrieved[:limit]:
        entry_id = item.get("entry_id") or item.get("id") or "?"
        score = item.get("score")
        if score is not None:
            parts.append(f"{entry_id}@{float(score):.3f}")
        else:
            parts.append(str(entry_id))
    return ", ".join(parts) if parts else "-"


def format_turn(turn: TurnRecord, *, short: bool = False) -> str:
    lines = [
        (
            f"--- {turn.created_at} session {_short_session(turn.session_id)} "
            f"#{turn.sequence} ---"
        ),
        f"category: {turn.category or '-'}  flags: {', '.join(turn.flags) or '-'}",
        f"status: {turn.status}  score: {turn.top_score if turn.top_score is not None else '-'}",
        f"retrieved: {_retrieved_summary(turn)}",
        f"repair: {turn.repair or '-'}  connection: {turn.connection_used or '-'}",
    ]
    if turn.timings:
        lines.append(f"timings_ms: {turn.timings}")
    wrap = 120 if short else WRAP
    lines.append("Q: " + textwrap.fill(turn.visitor_message, width=wrap, subsequent_indent="   "))
    lines.append("A: " + textwrap.fill(turn.reply or "(empty)", width=wrap, subsequent_indent="   "))
    return "\n".join(lines)


def format_gap_group(group: GapGroup) -> str:
    lines = [
        f"[{group.count}x] {group.sample_question}",
        f"  normalized: {group.normalized}",
        f"  first: {group.first_seen}  last: {group.last_seen}",
    ]
    return "\n".join(lines)


def format_stats(stats: SummaryStats) -> str:
    lines = [
        f"answered rate: {stats.answered_rate:.1%}",
        f"no_answer rate: {stats.no_answer_rate:.1%}",
        f"avg total ms: {stats.avg_total_ms if stats.avg_total_ms is not None else '-'}",
        f"p95 total ms: {stats.p95_total_ms if stats.p95_total_ms is not None else '-'}",
        f"unavailable turns: {stats.unavailable_count}",
        "by connection:",
    ]
    for name, count in sorted(stats.by_connection.items()):
        lines.append(f"  {name}: {count}")
    lines.append("by day / category:")
    for day in stats.daily:
        cats = ", ".join(f"{k}={v}" for k, v in sorted(day.by_category.items()))
        lines.append(f"  {day.day}: {cats}")
    return "\n".join(lines)


def export_turns_md(turns: list[TurnRecord], *, short: bool = False) -> str:
    return "\n\n".join(format_turn(turn, short=short) for turn in turns)


def export_turns_csv(turns: list[TurnRecord]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "created_at",
            "session_id",
            "sequence",
            "category",
            "flags",
            "top_score",
            "status",
            "visitor_message",
            "reply",
        ]
    )
    for turn in turns:
        writer.writerow(
            [
                turn.created_at,
                turn.session_id,
                turn.sequence,
                turn.category or "",
                " ".join(turn.flags),
                turn.top_score if turn.top_score is not None else "",
                turn.status,
                turn.visitor_message,
                turn.reply,
            ]
        )
    return buffer.getvalue()


def write_export(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
