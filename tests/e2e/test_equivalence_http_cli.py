"""Spec §17: HTTP replies vs CLI at T=0 (identical text)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from tests.e2e.helpers import chat_json, post_chat

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm]

ACCEPTANCE = Path(__file__).with_name("acceptance_spec17.json")
TIMING: list[dict[str, object]] = []


@pytest.fixture(scope="module")
def spec_cases() -> list[dict]:
    return json.loads(ACCEPTANCE.read_text(encoding="utf-8"))


def _cli_ask(question: str) -> str:
    """Same api container env as HTTP tests."""
    root = Path(__file__).resolve().parents[2]
    run = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.dev.yml",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "src.chat",
            "--ask",
            question,
        ],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    if run.returncode != 0:
        return f"__cli_error__:{run.stderr.strip()}"
    return run.stdout.strip()


def test_http_matches_cli_single_turns(
    http_client, e2e_web_base, require_llm, spec_cases: list[dict]
) -> None:
    """Expected: each single-turn §17 question matches `python -m src.chat --ask`."""
    diffs: list[str] = []
    for row in spec_cases:
        if "turns" in row:
            continue
        q = row["question"]
        t0 = time.perf_counter()
        http_body = chat_json(post_chat(http_client, e2e_web_base, q))
        http_ms = (time.perf_counter() - t0) * 1000
        cli = _cli_ask(q)
        http_reply = http_body.get("reply", "")
        TIMING.append(
            {
                "id": row["id"],
                "question": q,
                "http_ms": round(http_ms, 1),
                "connection": http_body.get("debug", {}).get("connection_used"),
            }
        )
        if cli != http_reply:
            diffs.append(f"{row['id']}: cli={cli[:80]!r} http={http_reply[:80]!r}")
    if diffs:
        pytest.fail("HTTP vs CLI differences:\n" + "\n".join(diffs))


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


def test_write_timing_report(tmp_path_factory, spec_cases: list[dict]) -> None:
    """Write timing JSON when RUN_E2E=1 (evidence for report)."""
    if not TIMING:
        pytest.skip("timing collected only when equivalence test ran")
    out = Path(__file__).resolve().parents[2] / "data" / "e2e"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "timing_http.json"
    path.write_text(json.dumps(TIMING, indent=2), encoding="utf-8")
