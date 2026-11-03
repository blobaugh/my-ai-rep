"""One live API turn. Skipped unless RUN_INTEGRATION=1."""

from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from src.api.app import create_app
from src.config import load_settings
from src.pipeline import answer_turn
from src.store import Store


def test_live_api_reply_matches_answer_turn(tmp_path) -> None:
    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("set RUN_INTEGRATION=1 to hit live Ollama")
    settings = load_settings()
    store = Store(
        tmp_path / "live.sqlite",
        idle_minutes=settings.session_idle_minutes,
        max_messages=settings.session_max_messages,
    )
    app = create_app(settings=settings, store=store)
    question = "Who is Ben?"
    direct = answer_turn(question, [], settings)
    response = TestClient(app).post("/api/chat", json={"message": question})
    assert response.status_code == 200
    assert response.json()["reply"] == direct.text
