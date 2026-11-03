"""Review aggregations and filters."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import mean

from src.review.db import fetch_turns
from src.review.normalize import normalize_question
from src.store import TurnRecord

GAP_FLAGS = frozenset({"weak_retrieval", "repair_fallback"})
GUARD_CATEGORIES = frozenset({"guard_identity", "guard_override"})


@dataclass(frozen=True)
class GapGroup:
    normalized: str
    sample_question: str
    count: int
    first_seen: str
    last_seen: str
    turns: tuple[TurnRecord, ...]


def is_gap_turn(turn: TurnRecord) -> bool:
    if turn.category == "no_answer":
        return True
    return any(flag in GAP_FLAGS for flag in turn.flags)


def gap_groups(
    conn,
    *,
    since: str | None = None,
    limit: int | None = None,
    min_count: int = 1,
) -> list[GapGroup]:
    turns = fetch_turns(conn, since=since, status="ok")
    gap_turns = [turn for turn in turns if is_gap_turn(turn)]
    buckets: dict[str, list[TurnRecord]] = defaultdict(list)
    for turn in gap_turns:
        buckets[normalize_question(turn.visitor_message)].append(turn)
    groups: list[GapGroup] = []
    for normalized, items in buckets.items():
        if len(items) < min_count:
            continue
        items.sort(key=lambda row: row.created_at)
        groups.append(
            GapGroup(
                normalized=normalized,
                sample_question=items[-1].visitor_message,
                count=len(items),
                first_seen=items[0].created_at,
                last_seen=items[-1].created_at,
                turns=tuple(items),
            )
        )
    groups.sort(key=lambda group: group.last_seen, reverse=True)
    if limit is not None:
        groups = groups[:limit]
    return groups


def failover_turns(conn, *, since: str | None = None) -> list[TurnRecord]:
    turns = fetch_turns(conn, since=since, status="ok")
    result: list[TurnRecord] = []
    for turn in turns:
        if turn.failover_active or "failover_used" in turn.flags:
            result.append(turn)
            continue
        if turn.connection_used and "secondary" in turn.connection_used.lower():
            result.append(turn)
    return result


@dataclass(frozen=True)
class DailyStats:
    day: str
    by_category: dict[str, int]


@dataclass(frozen=True)
class SummaryStats:
    daily: tuple[DailyStats, ...]
    answered_rate: float
    no_answer_rate: float
    avg_total_ms: float | None
    p95_total_ms: float | None
    by_connection: dict[str, int]
    unavailable_count: int


def _total_ms(turn: TurnRecord) -> int | None:
    if not turn.timings:
        return None
    total = turn.timings.get("total")
    if total is None:
        return None
    return int(total)


def compute_stats(conn, *, since: str | None = None) -> SummaryStats:
    turns = fetch_turns(conn, since=since, status="ok")
    daily: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: list[int] = []
    by_connection: dict[str, int] = defaultdict(int)
    answered = 0
    no_answer = 0
    for turn in turns:
        day = turn.created_at[:10]
        cat = turn.category or "unknown"
        daily[day][cat] += 1
        if turn.category == "answered":
            answered += 1
        if turn.category == "no_answer":
            no_answer += 1
        ms = _total_ms(turn)
        if ms is not None:
            totals.append(ms)
        conn_name = turn.connection_used or "unknown"
        by_connection[conn_name] += 1
    unavailable = len(fetch_turns(conn, since=since, status="unavailable"))
    total_ok = len(turns) or 1
    daily_rows = tuple(
        DailyStats(day=day, by_category=dict(cats))
        for day, cats in sorted(daily.items())
    )
    avg_total = mean(totals) if totals else None
    p95 = None
    if totals:
        ordered = sorted(totals)
        idx = max(0, int(len(ordered) * 0.95) - 1)
        p95 = float(ordered[idx])
    return SummaryStats(
        daily=daily_rows,
        answered_rate=answered / total_ok,
        no_answer_rate=no_answer / total_ok,
        avg_total_ms=avg_total,
        p95_total_ms=p95,
        by_connection=dict(by_connection),
        unavailable_count=unavailable,
    )


def parse_since(value: str) -> str:
    """Accept YYYY-MM-DD or ISO timestamp."""
    if "T" in value:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        return value
    datetime.strptime(value, "%Y-%m-%d")
    return f"{value}T00:00:00Z"
