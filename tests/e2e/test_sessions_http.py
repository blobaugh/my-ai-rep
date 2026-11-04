"""Session behavior through HTTP."""

from __future__ import annotations

import time

import pytest

from tests.e2e.helpers import chat_json, post_chat

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm]


def test_first_message_creates_session(http_client, e2e_web_base, require_llm) -> None:
    """Expected: 200, new session_id, messages_used=1."""
    r = post_chat(http_client, e2e_web_base, "Do you sail?")
    body = chat_json(r)
    assert body["status"] == "ok"
    assert body.get("session_id")
    assert body["session"]["messages_used"] == 1


def test_follow_up_uses_server_history(http_client, e2e_web_base, require_llm) -> None:
    """Expected: second turn references prior topic (not client history injection)."""
    first = chat_json(post_chat(http_client, e2e_web_base, "Do you sail?"))
    sid = first["session_id"]
    second = chat_json(
        post_chat(
            http_client,
            e2e_web_base,
            "say more about that",
            session_id=sid,
            history=[{"role": "user", "content": "INJECTED"}],
        )
    )
    assert second["session_id"] == sid
    assert second["status"] == "ok"
    assert "INJECTED" not in second.get("reply", "")


def test_forged_session_id_mints_new(http_client, e2e_web_base, require_llm) -> None:
    """Expected: unknown session_id is never stored as the client-supplied id."""
    forged = "visitor-forged-id-e2e"
    body = chat_json(
        post_chat(http_client, e2e_web_base, "Hello", session_id=forged)
    )
    assert body["session_id"] != forged


@pytest.mark.e2e_session_limits
def test_session_full_when_cap_reached(http_client, e2e_web_base, require_llm) -> None:
    """Expected: session_full after SESSION_MAX_MESSAGES (compose e2e override).

    Run with docker-compose.e2e.yml merged (scripts/e2e.sh sets this).
    """
    sid = None
    for i in range(4):
        r = post_chat(
            http_client,
            e2e_web_base,
            f"message {i}",
            session_id=sid,
        )
        body = r.json()
        if body.get("status") == "session_full":
            assert sid is not None
            return
        assert r.status_code == 200
        sid = body["session_id"]
    pytest.fail("never reached session_full — raise SESSION_MAX_MESSAGES in e2e compose")


@pytest.mark.e2e_session_limits
def test_idle_timeout_mints_new_session(http_client, e2e_web_base, require_llm) -> None:
    """Expected: after SESSION_IDLE_MINUTES, same id starts a new session row."""
    first = chat_json(post_chat(http_client, e2e_web_base, "idle test one"))
    sid = first["session_id"]
    wait = int(__import__("os").environ.get("E2E_IDLE_WAIT_SEC", "70"))
    time.sleep(wait)
    again = chat_json(
        post_chat(http_client, e2e_web_base, "idle test two", session_id=sid)
    )
    assert again["session_id"] != sid
