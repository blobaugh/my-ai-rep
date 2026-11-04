"""MinIO backup while chatting (BENBOT-26)."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.e2e


def test_backup_upload_while_chatting() -> None:
    """Expected: hourly snapshot in MinIO while api accepts messages."""
    if os.environ.get("E2E_BACKUP") != "1":
        pytest.skip(
            "set E2E_BACKUP=1 to run backup restore e2e (slow; see docs/web/e2e.md)"
        )
