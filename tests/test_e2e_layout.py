"""E2E suite layout (BENBOT-32) — no Docker required."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_e2e_runner_and_docs_exist() -> None:
    assert (ROOT / "scripts" / "e2e.sh").is_file()
    assert (ROOT / "docs" / "web" / "e2e.md").is_file()
    assert (ROOT / "docker-compose.e2e.yml").is_file()


def test_e2e_modules_cover_scenarios() -> None:
    e2e = ROOT / "tests" / "e2e"
    names = {p.name for p in e2e.glob("test_*.py")}
    for required in (
        "test_stack_security.py",
        "test_sessions_http.py",
        "test_limits_http.py",
        "test_equivalence_http_cli.py",
        "test_privacy.py",
        "test_review_flagging.py",
        "test_failover_embedder.py",
        "test_backup_restore.py",
        "test_ingest_serving.py",
        "test_ui_browser.py",
        "test_injection_http.py",
    ):
        assert required in names
