"""One backup cycle: snapshot, compress, upload, optional ping."""

from __future__ import annotations

import logging
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.backup import spaces
from src.backup.naming import daily_key, hourly_key, is_daily_run
from src.backup.settings import BackupSettings, require_spaces
from src.backup.snapshot import snapshot_database

logger = logging.getLogger(__name__)


def _resolve_db(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    root = Path(__file__).resolve().parents[2]
    return root / candidate


def run_backup(settings: BackupSettings, *, when: datetime | None = None) -> list[str]:
    """Return uploaded object keys. Raises on failure (no ping)."""
    require_spaces(settings)
    moment = when or datetime.now(timezone.utc)
    db_path = _resolve_db(settings.db_path)
    work = Path(tempfile.mkdtemp(prefix="benbot-backup-"))
    uploaded: list[str] = []
    try:
        snapshot = work / "benbot.sqlite"
        snapshot_database(db_path, snapshot)
        compressed = work / "benbot.sqlite.gz"
        spaces.compress_file(snapshot, compressed)
        hourly = hourly_key(settings.spaces_prefix, moment)
        spaces.upload_file(settings, compressed, hourly)
        uploaded.append(hourly)
        logger.info("uploaded %s", hourly)
        if is_daily_run(moment):
            daily = daily_key(settings.spaces_prefix, moment)
            spaces.upload_file(settings, compressed, daily)
            uploaded.append(daily)
            logger.info("uploaded %s", daily)
        if settings.backup_content and is_daily_run(moment):
            content_root = Path(settings.content_dir)
            if not content_root.is_absolute():
                content_root = Path(__file__).resolve().parents[2] / content_root
            if content_root.is_dir():
                archive = work / "content.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    tar.add(content_root, arcname="content")
                day = moment.strftime("%Y%m%d")
                prefix = settings.spaces_prefix.strip("/")
                content_key = (
                    f"{prefix}/daily/content-{day}.tar.gz"
                    if prefix
                    else f"daily/content-{day}.tar.gz"
                )
                spaces.upload_file(settings, archive, content_key)
                uploaded.append(content_key)
                logger.info("uploaded %s", content_key)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    ping = settings.backup_ping_url.strip()
    if ping:
        spaces.ping_success(ping)
    return uploaded
