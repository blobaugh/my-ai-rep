"""Failover scenario (optional compose override)."""

from __future__ import annotations

import os

import pytest

from tests.e2e.helpers import chat_json, compose_exec, post_chat

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm, pytest.mark.e2e_failover]


def test_failover_primary_dead(http_client, e2e_web_base, require_llm) -> None:
    """Expected: chat succeeds on secondary; review failovers lists the turn."""
    if os.environ.get("E2E_FAILOVER") != "1":
        pytest.skip(
            "set E2E_FAILOVER=1, merge docker-compose.e2e-failover.yml, "
            "and configure LLM_SECONDARY_* (see docs/web/e2e.md)"
        )

    body = chat_json(
        post_chat(http_client, e2e_web_base, "Reply with exactly: failover-check")
    )
    assert body["status"] == "ok"
    assert body.get("reply")

    review = compose_exec(
        "api",
        "python",
        "-m",
        "src.review",
        "failovers",
        "--since",
        "24h",
    )
    if review.returncode != 0:
        pytest.fail(review.stderr or review.stdout)
    first_line = review.stdout.strip().splitlines()[0]
    count = int(first_line.split()[0])
    assert count >= 1, review.stdout
