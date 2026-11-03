"""Concurrency and daily admission before a turn is accepted."""

from __future__ import annotations

import threading

from src.config import Settings
from src.store import Store


class TurnSlots:
    """Semaphore for in-flight pipeline calls plus a SQLite-backed daily cap."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        limit = settings.max_concurrent_turns
        self._sem = (
            threading.BoundedSemaphore(limit) if limit > 0 else None
        )

    def admission(self, store: Store) -> str | None:
        cap = self._settings.daily_message_cap
        if cap > 0 and store.messages_since_utc_midnight() >= cap:
            return "daily_limit"
        return None

    def acquire(self) -> bool:
        if self._sem is None:
            return True
        return self._sem.acquire(timeout=self._settings.busy_wait_seconds)

    def release(self) -> None:
        if self._sem is not None:
            self._sem.release()


def admission(settings: Settings, store: Store) -> str | None:
    """Legacy hook; ``create_app`` uses ``TurnSlots`` directly."""
    return TurnSlots(settings).admission(store)
