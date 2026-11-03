"""Backup scheduler and restore helper."""

from __future__ import annotations

import argparse
import gzip
import logging
import shutil
import sys
import time
from pathlib import Path

from src.backup import spaces
from src.backup.run import run_backup
from src.backup.settings import load_backup_settings, require_spaces
from src.backup.snapshot import integrity_ok
from src.config import configure_logging, load_settings


def _configure_logging() -> None:
    configure_logging(load_settings())


def _restore(settings, key: str, target: str) -> int:
    require_spaces(settings)
    work = Path("/tmp/benbot-restore")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    gz_path = work / "download.db.gz"
    db_path = Path(target)
    spaces.download_file(settings, key, gz_path)
    plain = work / "benbot.sqlite"
    with gzip.open(gz_path, "rb") as gz, plain.open("wb") as out:
        shutil.copyfileobj(gz, out)
    if not integrity_ok(plain):
        print("error: integrity_check failed on downloaded snapshot", file=sys.stderr)
        return 1
    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plain, db_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    print(f"restored {key} -> {db_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite backup to Spaces")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Run one backup cycle")
    restore_p = sub.add_parser("restore", help="Download one object into DB_PATH")
    restore_p.add_argument("object_key")
    restore_p.add_argument(
        "target",
        nargs="?",
        default="",
        help="Destination sqlite path (default: DB_PATH from settings)",
    )
    sub.add_parser("list", help="List remote backup keys")
    sub.add_parser("loop", help="Run backups on BACKUP_INTERVAL_MINUTES")

    args = parser.parse_args(argv)
    command = args.command or "loop"
    _configure_logging()
    settings = load_backup_settings()

    if command == "run":
        try:
            keys = run_backup(settings)
        except (OSError, RuntimeError, ValueError) as exc:
            logging.getLogger(__name__).error("%s", exc)
            return 1
        for key in keys:
            print(key)
        return 0

    if command == "loop":
        interval = max(1, settings.backup_interval_minutes) * 60
        log = logging.getLogger(__name__)
        while True:
            try:
                keys = run_backup(settings)
                log.info("backup ok: %s", ", ".join(keys))
            except (OSError, RuntimeError, ValueError) as exc:
                log.error("backup failed: %s", exc)
            time.sleep(interval)

    if command == "list":
        require_spaces(settings)
        prefix = settings.spaces_prefix.strip("/")
        search = f"{prefix}/" if prefix else ""
        for key in spaces.list_keys(settings, search):
            print(key)
        return 0

    if command == "restore":
        target = args.target or settings.db_path
        return _restore(settings, args.object_key, target)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
