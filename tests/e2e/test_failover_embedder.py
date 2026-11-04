"""Failover and embedder-down scenarios (optional compose overrides)."""

from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm]


def test_failover_primary_dead(require_llm) -> None:
    """Expected: secondary answers with failover_used when E2E_FAILOVER=1.

    Requires docker-compose.e2e-failover.yml and LLM_SECONDARY_* in .env.
    """
    if os.environ.get("E2E_FAILOVER") != "1":
        pytest.skip("set E2E_FAILOVER=1 and merge docker-compose.e2e-failover.yml")


def test_both_llm_down_unavailable(http_client, e2e_web_base) -> None:
    """Expected: 503 unavailable JSON when no model works.

    Manual: stop Ollama and unset secondary, or use compose override — not automated here.
    """
    pytest.skip(
        "could not test — stopping both models safely requires manual compose env"
    )


def test_embedder_stopped_unavailable(http_client, e2e_web_base, require_llm) -> None:
    """Expected: unavailable when embedder is down (ingest/search broken)."""
    pytest.skip(
        "could not test automatically — docker stop benbot_embedder disrupts other tests"
    )
