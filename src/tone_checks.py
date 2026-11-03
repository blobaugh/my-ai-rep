"""Advisory tone / topic-leak checks for eval (never block answers)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any


def _word_pattern(word: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)


def find_leak_words(reply: str, leak_words: Sequence[str]) -> list[str]:
    """Return configured words found in reply, in list order, once each."""
    found: list[str] = []
    seen: set[str] = set()
    for word in leak_words:
        key = word.strip().lower()
        if not key or key in seen:
            continue
        if _word_pattern(key).search(reply):
            found.append(key)
            seen.add(key)
    return found


def topic_covers_word(word: str, allowed_topics: list[str] | None) -> bool:
    """True when allowed_topics lists this word. Matching is exact."""
    if not allowed_topics:
        return False
    allowed = {t.strip().lower() for t in allowed_topics if t and str(t).strip()}
    return word.strip().lower() in allowed


def check_topic_leaks(
    reply: str,
    allowed_topics: list[str] | None = None,
    leak_words: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Advisory flags for configured words not listed in allowed_topics.

    An empty word list stays quiet. There is no built-in topic vocabulary.
    """
    flags: list[dict[str, Any]] = []
    for word in find_leak_words(reply, leak_words):
        if topic_covers_word(word, allowed_topics):
            continue
        flags.append(
            {
                "check": "topic_leak",
                "ok": False,
                "detail": f"leaked word {word!r}",
                "leaked_word": word,
            }
        )
    return flags


def check_mentions_any(
    reply: str,
    needles: list[str] | None,
    *,
    check_name: str = "positive_mentions",
) -> dict[str, Any] | None:
    """Advisory positive check: reply should mention at least one needle."""
    if not needles:
        return None
    lower = reply.lower()
    ok = any(str(n).lower() in lower for n in needles)
    return {
        "check": check_name,
        "ok": ok,
        "detail": None
        if ok
        else f"expected one of {[str(n).lower() for n in needles]}",
    }
