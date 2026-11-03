"""Build the post-answer "From my blog:" block. Age is decided in code."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol


class SourcedChunk(Protocol):
    """Minimal fields needed to list a retrieved post."""

    title: str
    slug: str
    url: str
    published_at: str
    score: float


def parse_published_date(published_at: str) -> date | None:
    """Parse ISO date/datetime to a calendar date. Returns None if unusable."""
    raw = (published_at or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def add_calendar_years(d: date, years: int) -> date:
    """Add calendar years; Feb 29 → Feb 28 in non-leap target years."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def is_older_than_years(
    published: date, *, today: date, stale_years: int
) -> bool:
    """True when published is at least stale_years before today (calendar years).

    Exactly N years ago counts as older. Future publish dates are never older.
    """
    if stale_years < 0:
        raise ValueError("stale_years must be >= 0")
    if published > today:
        return False
    return add_calendar_years(published, stale_years) <= today


def format_month_year(published: date) -> str:
    """English month name and year, e.g. 'March 2021'."""
    return published.strftime("%B %Y")


def build_sources(
    chunks: Sequence[SourcedChunk],
    *,
    today: date,
    stale_years: int,
    max_sources: int = 3,
) -> str:
    """Format the harness-owned source list. Empty when no *blog* chunks.

    Q&A entries are never listed. Dedupes by slug, score order, caps at max_sources.
    """
    if not chunks or max_sources <= 0:
        return ""

    blog_chunks = [
        c
        for c in chunks
        if str(getattr(c, "source_type", "blog") or "blog") == "blog"
    ]
    if not blog_chunks:
        return ""

    # Assume caller passes score-ordered chunks; stable first-seen by slug.
    ordered = sorted(blog_chunks, key=lambda c: c.score, reverse=True)
    seen: set[str] = set()
    lines: list[str] = []
    for chunk in ordered:
        slug = chunk.slug or chunk.url
        if not slug or slug in seen:
            continue
        seen.add(slug)
        published = parse_published_date(chunk.published_at)
        month_year = format_month_year(published) if published else "unknown date"
        line = f"- {chunk.title} ({month_year}) {chunk.url}"
        if published and is_older_than_years(
            published, today=today, stale_years=stale_years
        ):
            line += (
                f" — older than {stale_years} years, may be out of date"
            )
        lines.append(line)
        if len(lines) >= max_sources:
            break

    if not lines:
        return ""
    return "From my blog:\n" + "\n".join(lines)
