"""Admission hook for later caps.

BENBOT-28 fills this in. A return of ``busy`` or ``daily_limit`` becomes
HTTP 429. ``None`` means the turn may proceed. This function does not look
at addresses.
"""

from __future__ import annotations

from src.config import Settings
from src.store import Store


def admission(_settings: Settings, _store: Store) -> str | None:
    return None
