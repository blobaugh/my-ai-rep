"""HTTP API. One worker. Routes live under /api in this process."""

from src.api.app import create_app

__all__ = ["create_app"]
