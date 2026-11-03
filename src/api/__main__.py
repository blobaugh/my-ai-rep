"""Start one API worker. Fail fast on a bad config or a missing index.

An unreachable chat model does not stop startup. The Mac may be offline.
Run as ``python -m src.api``. One worker: failover state lives in this process.
"""

from __future__ import annotations

import sys

import uvicorn

from src.api.app import create_app
from src.config import configure_logging, format_settings, load_settings
from src.health import run_health_checks
from src.retrieve import load_index
from src.store import Store


def main() -> int:
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    configure_logging(settings)
    print(format_settings(settings))
    report = run_health_checks(settings)
    for warning in report.warnings:
        print(warning)
    blocking = [error for error in report.errors if "not reachable" not in error]
    reachable = [error for error in report.errors if "not reachable" in error]
    for error in reachable:
        print(error)
    if blocking:
        for error in blocking:
            print(error)
        return 1
    try:
        load_index()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    store = Store(
        settings.db_path,
        idle_minutes=settings.session_idle_minutes,
        max_messages=settings.session_max_messages,
    )
    app = create_app(settings=settings, store=store)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
