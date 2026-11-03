"""Backup container settings (read through src.config.load_settings)."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import load_settings


@dataclass(frozen=True)
class BackupSettings:
    db_path: str
    backup_interval_minutes: int
    spaces_endpoint: str
    spaces_bucket: str
    spaces_prefix: str
    spaces_key: str
    spaces_secret: str
    spaces_region: str
    spaces_addressing_style: str
    backup_ping_url: str
    backup_content: bool
    content_dir: str


def load_backup_settings() -> BackupSettings:
    settings = load_settings()
    return BackupSettings(
        db_path=settings.db_path,
        backup_interval_minutes=settings.backup_interval_minutes,
        spaces_endpoint=settings.spaces_endpoint,
        spaces_bucket=settings.spaces_bucket,
        spaces_prefix=settings.spaces_prefix,
        spaces_key=settings.spaces_key,
        spaces_secret=settings.spaces_secret,
        spaces_region=settings.spaces_region,
        spaces_addressing_style=settings.spaces_addressing_style,
        backup_ping_url=settings.backup_ping_url,
        backup_content=settings.backup_content == "on",
        content_dir=settings.content_dir,
    )


def require_spaces(settings: BackupSettings) -> None:
    missing = [
        name
        for name, value in (
            ("SPACES_ENDPOINT", settings.spaces_endpoint),
            ("SPACES_BUCKET", settings.spaces_bucket),
            ("SPACES_KEY", settings.spaces_key),
            ("SPACES_SECRET", settings.spaces_secret),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"backup requires: {', '.join(missing)}")
