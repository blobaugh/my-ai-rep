"""Question normalization for gap grouping."""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_question(text: str) -> str:
    lowered = text.strip().lower()
    stripped = _NON_WORD.sub("", lowered)
    return _WS.sub(" ", stripped).strip()
