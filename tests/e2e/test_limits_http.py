"""BENBOT-28 limits via real HTTP (needs docker-compose.e2e.yml)."""

from __future__ import annotations

import json
import threading
import time

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
    base = e2e_web_base
    # Long enough to overlap two turns while the model runs.
    message = (
        "In three detailed paragraphs, describe how you coach teams, "
        "including retros, tools, and habits."
    )
    results: list[httpx.Response | None] = [None, None]
    errors: list[BaseException | None] = [None, None]

    def worker(index: int) -> None:
        try:
            with httpx.Client(timeout=httpx.Timeout(180.0)) as client:
                results[index] = post_chat(client, base, f"{message} (turn {index + 1})")
        except BaseException as exc:  # noqa: BLE001 — capture thread errors for assertion
            errors[index] = exc

    t0 = threading.Thread(target=worker, args=(0,))
    t1 = threading.Thread(target=worker, args=(1,))
    t0.start()
    time.sleep(0.15)
    t1.start()
    t0.join(timeout=200)
    t1.join(timeout=200)

    assert errors[0] is None and errors[1] is None, (errors[0], errors[1])
    assert results[0] is not None and results[1] is not None
    bodies = []
    for resp in results:
        assert resp is not None
        try:
            bodies.append(resp.json())
        except json.JSONDecodeError:
            bodies.append({})
    statuses = {results[0].status_code, results[1].status_code}
    busy = any(b.get("status") == "busy" for b in bodies)
    assert busy, f"expected one busy response, got statuses={statuses} bodies={bodies}"
