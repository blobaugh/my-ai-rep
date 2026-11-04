"""HTTP helpers for e2e tests."""

from __future__ import annotations

from typing import Any

import httpx


def post_chat(
    client: httpx.Client,
    base: str,
    message: str,
    *,
    session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> httpx.Response:
    payload: dict[str, Any] = {"message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    if history is not None:
        payload["history"] = history
    return client.post(
        f"{base.rstrip('/')}/api/chat",
        json=payload,
        headers={"Content-Type": "application/json"},
    )


def chat_json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    return response.json()


def record_scenario(
    results: list[dict[str, str]],
    *,
    scenario: str,
    expected: str,
    actual: str,
    passed: bool,
    evidence: str = "",
) -> None:
    results.append(
        {
            "scenario": scenario,
            "expected": expected,
            "actual": actual,
            "result": "pass" if passed else "fail",
            "evidence": evidence,
        }
    )
