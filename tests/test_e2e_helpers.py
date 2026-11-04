"""Unit tests for e2e helper parsing (no Docker)."""

from __future__ import annotations

from pathlib import Path

from tests.e2e.helpers import strip_cli_ask_stdout


def test_strip_cli_ask_stdout_removes_warnings_and_settings() -> None:
    raw = """WARNING chat primary is not reachable at http://localhost:11434/v1.
Effective settings:
LLM_MODEL=llama3.1:8b
LLM_BASE_URL=http://localhost:11434/v1
Hello from the bot."""
    assert strip_cli_ask_stdout(raw) == "Hello from the bot."


def test_e2e_sh_records_real_pytest_exit_code() -> None:
    text = (Path(__file__).resolve().parents[1] / "scripts" / "e2e.sh").read_text(
        encoding="utf-8"
    )
    assert "pytest.log" in text
    assert "pytest_status=$?" in text
    assert "pytest tests/e2e" in text
    # Must not mask pytest exit status with tee on the same line as pytest.
    assert 'tee "$report_dir/pytest.log"' not in text
