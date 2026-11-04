"""Privacy: SQLite schema and logs (no IP / user agent)."""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.e2e


def test_sqlite_schema_has_no_ip_or_ua_columns(docker_available: bool) -> None:
    """Expected: sessions/turns tables store no network identifiers."""
    if not docker_available:
        pytest.skip("docker not available")
    script = """
import sqlite3
conn = sqlite3.connect("/app/data/benbot.sqlite")
for table in ("sessions", "turns"):
    cols = [r[1].lower() for r in conn.execute(f"PRAGMA table_info({table})")]
    for forbidden in ("ip", "user_agent", "user-agent", "remote_addr"):
        assert forbidden not in cols, (table, cols)
print("ok")
"""
    run = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.dev.yml",
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        cwd=__import__("pathlib").Path(__file__).resolve().parents[2],
        check=False,
    )
    if run.returncode != 0 and "no such file" in (run.stderr + run.stdout):
        pytest.skip("database not created yet — send a chat message first")
    assert run.returncode == 0, run.stderr or run.stdout
