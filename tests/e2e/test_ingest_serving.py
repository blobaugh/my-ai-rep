"""Ingest while API serves traffic."""

from __future__ import annotations

import subprocess

import pytest

from tests.e2e.helpers import chat_json, post_chat

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm]


def test_ingest_while_api_healthy(http_client, e2e_web_base, require_llm) -> None:
    """Expected: ingest completes while /api/health stays 200."""
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    before = http_client.get(f"{e2e_web_base}/api/health")
    assert before.status_code == 200
    ingest = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.dev.yml",
            "run",
            "--rm",
            "ingest",
        ],
        capture_output=True,
        text=True,
        cwd=root,
        timeout=600,
        check=False,
    )
    assert ingest.returncode == 0, ingest.stderr[-2000:]
    after = http_client.get(f"{e2e_web_base}/api/health")
    assert after.status_code == 200
    chat_json(post_chat(http_client, e2e_web_base, "Who is Ben?"))
