"""HTTP routing and CLI smoke. Exact pipeline parity: tests/test_api_live.py (integration)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.e2e.helpers import chat_json, cli_ask_in_api_container, post_chat

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm]

ACCEPTANCE = Path(__file__).with_name("acceptance_spec17.json")
TIMING: list[dict[str, object]] = []


@pytest.fixture(scope="module")
def spec_cases() -> list[dict]:
    return json.loads(ACCEPTANCE.read_text(encoding="utf-8"))


def test_web_and_api_return_same_validation_error(http_client, e2e_web_base, e2e_api_base) -> None:
    """Expected: dev nginx proxy forwards /api unchanged (no LLM; deterministic)."""
    long_msg = "a" * 2000
    via_web = post_chat(http_client, e2e_web_base, long_msg)
    via_api = post_chat(http_client, e2e_api_base, long_msg)
    assert via_web.status_code == via_api.status_code == 400
    assert via_web.json() == via_api.json()


def test_web_and_api_health_identical(http_client, e2e_web_base, e2e_api_base) -> None:
    assert http_client.get(f"{e2e_web_base}/api/health").json() == http_client.get(
        f"{e2e_api_base}/api/health"
    ).json()


def test_spec_questions_return_ok_via_web(
    http_client, e2e_web_base, require_llm, spec_cases: list[dict]
) -> None:
    """Expected: spec §17 single-turn questions succeed over HTTP (timing evidence)."""
    for row in spec_cases:
        if "turns" in row:
            continue
        q = row["question"]
        t0 = time.perf_counter()
        body = chat_json(post_chat(http_client, e2e_web_base, q))
        TIMING.append(
            {
                "id": row["id"],
                "question": q,
                "http_ms": round((time.perf_counter() - t0) * 1000, 1),
                "status": body.get("status"),
            }
        )
        assert body.get("status") == "ok", row["id"]


def test_cli_ask_smoke_matches_http_persona(
    http_client, e2e_web_base, require_llm
) -> None:
    """Expected: CLI --ask and HTTP both return a non-empty AI-labeled answer."""
    q = "Who is Ben?"
    http_reply = chat_json(post_chat(http_client, e2e_web_base, q)).get("reply", "")
    cli_reply = cli_ask_in_api_container(q)
    for text in (http_reply, cli_reply):
        assert len(text.strip()) > 10
        assert "ai" in text.lower(), text[:200]


def test_http_s1_second_turn_not_coaching(
    http_client, e2e_web_base, require_llm, spec_cases: list[dict]
) -> None:
    """Expected: acc-9 turn 2 does not mention coach/retro (spec S1)."""
    s1 = next(c for c in spec_cases if c.get("id") == "acc-9")
    first = chat_json(post_chat(http_client, e2e_web_base, s1["turns"][0]["question"]))
    second = chat_json(
        post_chat(
            http_client,
            e2e_web_base,
            s1["turns"][1]["question"],
            session_id=first["session_id"],
        )
    )
    reply = second.get("reply", "").lower()
    assert "coach" not in reply and "retro" not in reply


def test_write_timing_report(spec_cases: list[dict]) -> None:
    """Write timing JSON when RUN_E2E=1 (evidence for report)."""
    if not TIMING:
        pytest.skip("timing collected only when spec HTTP test ran")
    out = Path(__file__).resolve().parents[2] / "data" / "e2e"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "timing_http.json"
    path.write_text(json.dumps(TIMING, indent=2), encoding="utf-8")
