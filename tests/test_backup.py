"""Backup naming, snapshot, Spaces upload, and CLI behavior."""

from __future__ import annotations

import gzip
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.backup import spaces
from src.backup.naming import daily_key, hourly_key, is_daily_run
from src.backup.run import run_backup
from src.backup.settings import BackupSettings
from src.backup.snapshot import integrity_ok, snapshot_database
from src.config import load_settings


def _settings(**overrides) -> BackupSettings:
    base = {
        "db_path": "data/benbot.sqlite",
        "backup_interval_minutes": 60,
        "spaces_endpoint": "http://minio:9000",
        "spaces_bucket": "test-bucket",
        "spaces_prefix": "dev",
        "spaces_key": "key",
        "spaces_secret": "secret",
        "spaces_region": "us-east-1",
        "spaces_addressing_style": "path",
        "backup_ping_url": "",
        "backup_content": False,
        "content_dir": "content",
    }
    base.update(overrides)
    return BackupSettings(**base)


def test_hourly_and_daily_keys() -> None:
    when = datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc)
    assert hourly_key("benbot/prod", when) == (
        "benbot/prod/hourly/benbot-20261031T160000Z.db.gz"
    )
    assert daily_key("benbot/prod", when) == (
        "benbot/prod/daily/benbot-20261031T160000Z.db.gz"
    )


def test_is_daily_run_at_midnight_utc() -> None:
    assert is_daily_run(datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc))
    assert not is_daily_run(datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc))


def test_snapshot_while_wal_writes(tmp_path) -> None:
    live = tmp_path / "live.sqlite"
    conn = sqlite3.connect(live)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    stop = threading.Event()

    def writer() -> None:
        wconn = sqlite3.connect(live)
        n = 0
        while not stop.is_set():
            wconn.execute("INSERT INTO t (v) VALUES (?)", (f"row-{n}",))
            wconn.commit()
            n += 1
        wconn.close()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        dest = tmp_path / "snap.sqlite"
        snapshot_database(live, dest)
        assert integrity_ok(dest)
        count = sqlite3.connect(dest).execute("SELECT COUNT(*) FROM t").fetchone()[0]
        assert count > 0
    finally:
        stop.set()
        thread.join(timeout=2)
        conn.close()


def test_run_backup_pings_only_on_success(tmp_path, monkeypatch) -> None:
    db = tmp_path / "benbot.sqlite"
    sqlite3.connect(db).close()
    settings = _settings(db_path=str(db), backup_ping_url="http://ping.example/ok")
    uploads: list[str] = []

    def fake_upload(_settings, path, key) -> int:
        uploads.append(key)
        return path.stat().st_size

    ping = MagicMock()
    monkeypatch.setattr(spaces, "upload_file", fake_upload)
    monkeypatch.setattr(spaces, "ping_success", ping)

    keys = run_backup(settings, when=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc))
    assert keys
    ping.assert_called_once_with("http://ping.example/ok")


def test_run_backup_skips_ping_on_upload_failure(tmp_path, monkeypatch) -> None:
    db = tmp_path / "benbot.sqlite"
    sqlite3.connect(db).close()
    settings = _settings(db_path=str(db), backup_ping_url="http://ping.example/ok")
    ping = MagicMock()

    def boom(*_args, **_kwargs):
        raise RuntimeError("upload failed")

    monkeypatch.setattr(spaces, "upload_file", boom)
    monkeypatch.setattr(spaces, "ping_success", ping)

    with pytest.raises(RuntimeError, match="upload failed"):
        run_backup(settings)
    ping.assert_not_called()


def test_cli_run_returns_nonzero_on_failure(monkeypatch) -> None:
    from src.backup import __main__ as cli

    def boom(_settings):
        raise RuntimeError("no bucket")

    monkeypatch.setattr(cli, "load_backup_settings", lambda: _settings())
    monkeypatch.setattr(cli, "run_backup", boom)
    monkeypatch.setattr(cli, "_configure_logging", lambda: None)

    assert cli.main(["run"]) == 1


def test_spaces_secrets_masked_in_settings_log(monkeypatch) -> None:
    monkeypatch.setenv("SPACES_KEY", "super-secret-key")
    monkeypatch.setenv("SPACES_SECRET", "super-secret-value")
    masked = load_settings().masked_dict()
    assert "super-secret" not in str(masked.values())
    assert masked["SPACES_KEY"] != "super-secret-key"
    assert masked["SPACES_SECRET"] != "super-secret-value"


def test_addressing_style_auto_for_minio() -> None:
    settings = _settings(
        spaces_endpoint="http://minio:9000",
        spaces_addressing_style="auto",
    )
    assert spaces._addressing_style(settings) == "path"


@pytest.mark.integration
def test_minio_backup_and_restore_roundtrip(tmp_path) -> None:
    if os.environ.get("RUN_BACKUP_INTEGRATION") != "1":
        pytest.skip("set RUN_BACKUP_INTEGRATION=1 and start MinIO (dev compose)")

    pytest.importorskip("boto3")

    endpoint = os.environ.get("SPACES_ENDPOINT", "http://127.0.0.1:9000")
    bucket = os.environ.get("SPACES_BUCKET", "benbot-backups")
    settings = _settings(
        db_path=str(tmp_path / "live.sqlite"),
        spaces_endpoint=endpoint,
        spaces_bucket=bucket,
        spaces_key=os.environ.get("SPACES_KEY", "minioadmin"),
        spaces_secret=os.environ.get("SPACES_SECRET", "minioadmin"),
        spaces_prefix="integration",
        spaces_addressing_style="path",
    )

    live = Path(settings.db_path)
    conn = sqlite3.connect(live)
    conn.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, note TEXT)")
    conn.execute("INSERT INTO probe (note) VALUES ('before-backup')")
    conn.commit()
    conn.close()

    client = spaces._client(settings)
    from botocore.exceptions import ClientError

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)

    when = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
    keys = run_backup(settings, when=when)
    assert keys

    restored = tmp_path / "restored.sqlite"
    gz_path = tmp_path / "dl.gz"
    spaces.download_file(settings, keys[0], gz_path)
    with gzip.open(gz_path, "rb") as gz, restored.open("wb") as out:
        out.write(gz.read())
    assert integrity_ok(restored)
    note = sqlite3.connect(restored).execute(
        "SELECT note FROM probe LIMIT 1"
    ).fetchone()[0]
    assert note == "before-backup"
