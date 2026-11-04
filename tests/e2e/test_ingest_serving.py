"""Ingest while API serves traffic."""

from __future__ import annotations

import pytest

from tests.e2e.helpers import chat_json, post_chat, run_ingest_via_api_exec

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm]


def test_ingest_while_api_healthy(http_client, e2e_web_base, require_llm) -> None:
    """Expected: ingest completes while /api/health stays 200."""
    before = http_client.get(f"{e2e_web_base}/api/health")
    assert before.status_code == 200
    ingest = run_ingest_via_api_exec()
    assert ingest.returncode == 0, (ingest.stderr or ingest.stdout)[-2000:]
    after = http_client.get(f"{e2e_web_base}/api/health")
    assert after.status_code == 200
    chat_json(post_chat(http_client, e2e_web_base, "Who is Ben?"))
