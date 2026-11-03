"""Object key names for hourly and daily snapshots."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_stamp(when: datetime | None = None) -> str:
    moment = when or datetime.now(timezone.utc)
    return moment.strftime("%Y%m%dT%H%M%SZ")


def hourly_key(prefix: str, when: datetime | None = None) -> str:
    base = prefix.strip("/")
    stamp = utc_stamp(when)
    name = f"benbot-{stamp}.db.gz"
    return f"{base}/hourly/{name}" if base else f"hourly/{name}"


def daily_key(prefix: str, when: datetime | None = None) -> str:
    base = prefix.strip("/")
    stamp = utc_stamp(when)
    name = f"benbot-{stamp}.db.gz"
    return f"{base}/daily/{name}" if base else f"daily/{name}"


def is_daily_run(when: datetime | None = None) -> bool:
    moment = when or datetime.now(timezone.utc)
    return moment.hour == 0
