"""Unit tests for advisory topic-leak and positive tone checks."""

from __future__ import annotations

import json
from pathlib import Path

from src.tone_checks import (
    check_mentions_any,
    check_topic_leaks,
    find_leak_words,
    topic_covers_word,
)


def test_find_leak_words_case_insensitive() -> None:
    text = "We had Breakfast on the Boat before Sailing."
    assert find_leak_words(text) == ["breakfast", "boat", "sailing"]


def test_leak_check_flags_when_not_allowed() -> None:
    flags = check_topic_leaks(
        "I love sailing on Saturday with the kids.",
        allowed_topics=[],
    )
    leaked = {f["leaked_word"] for f in flags}
    assert leaked == {"sailing", "saturday", "kids"}
    assert all(not f["ok"] for f in flags)


def test_leak_check_ignores_allowed_topics() -> None:
    flags = check_topic_leaks(
        "I love sailing on Saturday with the kids.",
        allowed_topics=["sailing", "saturday", "kids"],
    )
    assert flags == []


def test_leak_check_fun_topic_covers_related_words() -> None:
    flags = check_topic_leaks(
        "Bees in the apiary, then breakfast in the garden.",
        allowed_topics=["fun"],
    )
    assert flags == []


def test_topic_covers_word_direct_and_mapped() -> None:
    assert topic_covers_word("boat", ["sailing"])
    assert topic_covers_word("boat", ["boat"])
    assert not topic_covers_word("boat", [])
    assert not topic_covers_word("boat", ["garden"])


def test_positive_mentions_ok_and_fail() -> None:
    ok = check_mentions_any(
        "I sail and keep bees.",
        ["sailing", "bees", "garden", "kids", "boat"],
    )
    assert ok is not None and ok["ok"] is True
    bad = check_mentions_any(
        "I like to read quietly.",
        ["sailing", "bees", "garden", "kids", "boat"],
    )
    assert bad is not None and bad["ok"] is False


def test_load_tone_cases_json() -> None:
    path = Path("eval/tone_cases.json")
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) == 8
    by_id = {c["id"]: c for c in cases}
    assert by_id["tone-ideal-role"]["allowed_topics"] == []
    assert "sailing" in by_id["tone-for-fun"]["allowed_topics"]
    assert by_id["tone-for-fun"]["expect_mentions_any"]
    assert by_id["tone-sailing-start"]["expect_mentions_any"]
    assert by_id["tone-work-for-gap"]["question"] == "What are you like to work for?"
