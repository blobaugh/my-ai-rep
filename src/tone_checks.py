"""Advisory tone / topic-leak checks for eval (never block answers)."""

from __future__ import annotations

import re
from typing import Any

# Words that suggest voice-sample / personal-life topic bleed into answers.
LEAK_WORDS: tuple[str, ...] = (
    "breakfast",
    "boat",
    "sail",
    "sailing",
    "bees",
    "apiary",
    "saturday",
    "garden",
    "kids",
)

# Map each leak word to topic tags that cover it when listed in allowed_topics.
LEAK_WORD_TOPICS: dict[str, frozenset[str]] = {
    "breakfast": frozenset({"breakfast", "saturday", "fun", "hobbies"}),
    "boat": frozenset({"boat", "sailing", "fun", "hobbies"}),
    "sail": frozenset({"sail", "sailing", "fun", "hobbies"}),
    "sailing": frozenset({"sailing", "fun", "hobbies"}),
    "bees": frozenset({"bees", "apiary", "fun", "hobbies"}),
    "apiary": frozenset({"apiary", "bees", "fun", "hobbies"}),
    "saturday": frozenset({"saturday", "fun", "hobbies"}),
    "garden": frozenset({"garden", "fun", "hobbies"}),
    "kids": frozenset({"kids", "family", "fun", "hobbies"}),
}


def _word_pattern(word: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)


def find_leak_words(reply: str) -> list[str]:
    """Return leak words found in reply (lowercase, unique, LEAK_WORDS order)."""
    found: list[str] = []
    for word in LEAK_WORDS:
        if _word_pattern(word).search(reply):
            found.append(word)
    return found


def topic_covers_word(word: str, allowed_topics: list[str] | None) -> bool:
    """True when allowed_topics covers this leak word."""
    if not allowed_topics:
        return False
    allowed = {t.strip().lower() for t in allowed_topics if t and str(t).strip()}
    if word.lower() in allowed:
        return True
    topics = LEAK_WORD_TOPICS.get(word.lower(), frozenset({word.lower()}))
    return bool(allowed & topics)


def check_topic_leaks(
    reply: str,
    allowed_topics: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Advisory flags for leak words not covered by allowed_topics."""
    flags: list[dict[str, Any]] = []
    for word in find_leak_words(reply):
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
