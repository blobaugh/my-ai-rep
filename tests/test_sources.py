"""Unit tests for age math and the From my blog sources block."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.sources import (
    add_calendar_years,
    build_sources,
    is_older_than_years,
    parse_published_date,
)


@dataclass(frozen=True)
class FakeChunk:
    title: str
    slug: str
    url: str
    published_at: str
    score: float


def test_exactly_n_years_is_stale() -> None:
    published = date(2021, 3, 15)
    today = date(2024, 3, 15)
    assert is_older_than_years(published, today=today, stale_years=3)


def test_one_day_under_n_years_is_not_stale() -> None:
    published = date(2021, 3, 16)
    today = date(2024, 3, 15)
    assert not is_older_than_years(published, today=today, stale_years=3)


def test_feb_29_rollover() -> None:
    published = date(2020, 2, 29)
    assert add_calendar_years(published, 1) == date(2021, 2, 28)
    # 4 calendar years later lands on Feb 29 again.
    assert add_calendar_years(published, 4) == date(2024, 2, 29)
    assert is_older_than_years(published, today=date(2023, 2, 28), stale_years=3)
    assert not is_older_than_years(
        published, today=date(2023, 2, 27), stale_years=3
    )


def test_future_date_never_stale() -> None:
    assert not is_older_than_years(
        date(2030, 1, 1), today=date(2024, 1, 1), stale_years=3
    )


def test_parse_published_date() -> None:
    assert parse_published_date("2021-03-15T12:00:00Z") == date(2021, 3, 15)
    assert parse_published_date("2021-03-15") == date(2021, 3, 15)
    assert parse_published_date("") is None


def test_build_sources_empty() -> None:
    assert build_sources([], today=date(2024, 1, 1), stale_years=3) == ""


def test_build_sources_omits_qa_entries() -> None:
    @dataclass(frozen=True)
    class TypedChunk:
        title: str
        slug: str
        url: str
        published_at: str
        score: float
        source_type: str

    chunks = [
        TypedChunk(
            "QA title",
            "intro",
            "",
            "",
            0.99,
            "qa",
        ),
        TypedChunk(
            "Proxy",
            "proxy",
            "https://example.com/proxy",
            "2021-03-01T00:00:00Z",
            0.8,
            "blog",
        ),
    ]
    text = build_sources(chunks, today=date(2024, 6, 1), stale_years=3)
    assert "From my blog:" in text
    assert "proxy" in text
    assert "intro" not in text
    assert "QA title" not in text
    only_qa = build_sources(chunks[:1], today=date(2024, 6, 1), stale_years=3)
    assert only_qa == ""


def test_build_sources_dedupe_order_cap_and_stale_suffix() -> None:
    chunks = [
        FakeChunk(
            "Proxy A",
            "proxy",
            "https://example.com/proxy",
            "2021-03-01T00:00:00Z",
            0.9,
        ),
        FakeChunk(
            "Proxy A again",
            "proxy",
            "https://example.com/proxy",
            "2021-03-01T00:00:00Z",
            0.8,
        ),
        FakeChunk(
            "Sailing",
            "sailing",
            "https://example.com/sailing",
            "2023-06-01T00:00:00Z",
            0.7,
        ),
        FakeChunk(
            "Old",
            "old",
            "https://example.com/old",
            "2018-01-01T00:00:00Z",
            0.6,
        ),
        FakeChunk(
            "Extra",
            "extra",
            "https://example.com/extra",
            "2022-01-01T00:00:00Z",
            0.5,
        ),
    ]
    text = build_sources(
        chunks, today=date(2024, 6, 1), stale_years=3, max_sources=3
    )
    assert text.startswith("From my blog:\n")
    assert text.count("https://example.com/proxy") == 1
    assert "Proxy A (March 2021)" in text
    assert "older than 3 years, may be out of date" in text
    assert "Sailing (June 2023)" in text
    # Cap at 3 unique slugs; lowest-score "extra" is dropped.
    assert "extra" not in text
    assert "Old (January 2018)" in text
