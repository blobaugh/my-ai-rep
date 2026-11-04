"""BENBOT-28 limits via real HTTP (needs docker-compose.e2e.yml)."""

from __future__ import annotations

import json

import httpx
import pytest

from tests.e2e.helpers import post_chat

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm]


def test_oversize_body_rejected(http_client, e2e_web_base, require_llm) -> None:
    """Expected: 413 or 400 for body > 8KB."""
    big = "x" * 9000
    r = post_chat(http_client, e2e_web_base, big)
    assert r.status_code in (400, 413, 422)


def test_overlong_message_rejected(http_client, e2e_web_base, require_llm) -> None:
    """Expected: validation error when message exceeds MESSAGE_MAX_CHARS."""
    long_msg = "a" * 2000
    r = post_chat(http_client, e2e_web_base, long_msg)
    assert r.status_code == 400
    assert r.json().get("status") == "invalid"


def test_wrong_content_type(http_client, e2e_web_base) -> None:
    """Expected: reject non-JSON content-type (no LLM needed)."""
    r = http_client.post(
        f"{e2e_web_base}/api/chat",
        content=b'{"message":"hi"}',
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 400


@pytest.mark.e2e_limits
def test_busy_when_concurrency_saturated(http_client, e2e_web_base, require_llm) -> None:
    """Expected: second in-flight chat returns busy (MAX_CONCURRENT_TURNS=1 in e2e compose)."""
    transport = httpx.Client(timeout=httpx.Timeout(180.0))
    base = e2e_web_base

    def slow_post(label: str) -> httpx.Response:
        return transport.post(
            f"{base}/api/chat",
            json={"message": label},
            headers={"Content-Type": "application/json"},
        )

    first = slow_post("slow-one")
    import time

    time.sleep(0.1)
    second = slow_post("slow-two")
    statuses = {first.status_code, second.status_code}
    bodies = []
    for resp in (first, second):
        try:
            bodies.append(resp.json())
        except json.JSONDecodeError:
            bodies.append({})
    busy = any(b.get("status") == "busy" for b in bodies)
    assert busy or 503 in statuses, bodies
    transport.close()
