"""HTTP API with a fake pipeline and a temporary database. No Ollama."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from starlette.testclient import TestClient

from src.api.app import create_app
from src.api.copy import SESSION_FULL, UNAVAILABLE
from src.config import load_settings
from src.llm_pool import ModelUnavailable
from src.outcomes import classify_turn
from src.pipeline import Answer
from src.store import Store


def _settings(**overrides: str):
    base = {
        "HUMAN_NAME": "Ada",
        "BOT_NAME": "AdaBot",
        "LLM_API_KEY": "test-secret-key",
        "MESSAGE_MAX_CHARS": "20",
        "SESSION_MAX_MESSAGES": "2",
        "SESSION_IDLE_MINUTES": "60",
        "HISTORY_TURNS": "6",
    }
    base.update(overrides)
    return load_settings(environ=base)


def _answer(question: str, history: list[dict[str, str]], settings) -> Answer:
    outcome = classify_turn(
        question,
        "I lead a team.",
        human_name=settings.human_name,
        bot_name=settings.bot_name,
        retrieved=[{"id": "qa#intro", "score": 0.8, "phrasing": "work", "sent": True}],
        connection_used="primary",
        timings={"embed": 0.1, "search": 0.0, "first_token": 0.2, "total": 0.3},
        prompt_tokens=11,
    )
    return Answer(
        text="I lead a team.",
        sources_block="",
        debug={
            "retrieved": [
                {"id": "qa#intro", "score": 0.8, "sent": True, "source_type": "qa"}
            ],
            "repair": "none",
            "connection_used": "primary",
            "failover_active": False,
            "category": outcome.category,
            "outcome_flags": list(outcome.flags),
            "top_score": outcome.top_score,
        },
        finish_reason="stop",
        outcome=outcome,
    )


def _app(tmp_path, settings=None, answer_fn=None, index_ok=None):
    settings = settings or _settings()
    store = Store(
        tmp_path / "api.sqlite",
        idle_minutes=settings.session_idle_minutes,
        max_messages=settings.session_max_messages,
    )
    seen: list[tuple[str, list[dict[str, str]]]] = []

    def record(question, history, _settings):
        seen.append((question, list(history)))
        if answer_fn is not None:
            return answer_fn(question, history, _settings)
        return _answer(question, history, _settings)

    app = create_app(
        settings=settings,
        store=store,
        answer_fn=record,
        index_ok=index_ok or (lambda: True),
    )
    return app, store, seen


def test_new_session_continue_and_stored_reply(tmp_path) -> None:
    app, store, seen = _app(tmp_path)
    client = TestClient(app)
    first = client.post("/api/chat", json={"message": "Who is Ada?"})
    assert first.status_code == 200
    body = first.json()
    assert body["reply"] == "I lead a team."
    assert body["status"] == "ok"
    assert body["session"] == {"messages_used": 1, "messages_max": 2}
    session_id = body["session_id"]
    assert session_id
    second = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "Say more",
            "history": [{"role": "user", "content": "INJECTED"}],
        },
    )
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id
    assert seen[1][1] == [
        {"role": "user", "content": "Who is Ada?"},
        {"role": "assistant", "content": "I lead a team."},
    ]
    assert "INJECTED" not in json.dumps(seen)
    stored = store.get_turn(session_id, 1)
    assert stored is not None
    assert stored.reply == "I lead a team."
    assert stored.category == "answered"
    assert stored.connection_used == "primary"
    assert stored.top_score == 0.8
    assert stored.prompt_tokens == 11
    assert stored.retrieved[0]["id"] == "qa#intro"


def test_unknown_and_expired_ids_mint_a_new_session(tmp_path) -> None:
    clock = {"now": __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)}
    settings = _settings()
    store = Store(
        tmp_path / "api.sqlite",
        idle_minutes=60,
        max_messages=5,
        clock=lambda: clock["now"],
    )
    app = create_app(
        settings=settings,
        store=store,
        answer_fn=_answer,
        index_ok=lambda: True,
    )
    client = TestClient(app)
    unknown = client.post(
        "/api/chat", json={"session_id": "visitor-picked", "message": "Hello"}
    )
    assert unknown.status_code == 200
    assert unknown.json()["session_id"] != "visitor-picked"
    assert store.message_count("visitor-picked") == 0
    first_id = unknown.json()["session_id"]
    from datetime import timedelta

    clock["now"] = clock["now"] + timedelta(minutes=61)
    expired = client.post(
        "/api/chat", json={"session_id": first_id, "message": "Again"}
    )
    assert expired.status_code == 200
    assert expired.json()["session_id"] != first_id


def test_session_full_empty_and_too_long(tmp_path) -> None:
    app, _store, seen = _app(tmp_path)
    client = TestClient(app)
    created = client.post("/api/chat", json={"message": "one"})
    client.post(
        "/api/chat",
        json={"session_id": created.json()["session_id"], "message": "two"},
    )
    full = client.post(
        "/api/chat",
        json={"session_id": created.json()["session_id"], "message": "three"},
    )
    assert full.status_code == 409
    assert full.json()["status"] == "session_full"
    assert full.json()["reply"] == SESSION_FULL
    assert len(seen) == 2
    empty = client.post("/api/chat", json={"message": "  \n"})
    assert empty.status_code == 400
    assert empty.json()["status"] == "invalid"
    long = client.post("/api/chat", json={"message": "x" * 21})
    assert long.status_code == 400
    assert long.json()["reply"].startswith("That message is too long")


def test_unavailable_is_logged_and_secrets_stay_out(tmp_path) -> None:
    def boom(_question, _history, _settings):
        raise ModelUnavailable("down")

    app, store, _seen = _app(tmp_path, answer_fn=boom)
    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 503
    assert response.json()["reply"] == UNAVAILABLE
    assert response.json()["status"] == "unavailable"
    assert "test-secret-key" not in response.text
    session_id = response.json()["session_id"]
    stored = store.get_turn(session_id, 1)
    assert stored is not None
    assert stored.status == "unavailable"
    assert stored.reply == UNAVAILABLE


def test_embedder_failure_is_unavailable(tmp_path) -> None:
    from src.embeddings import EmbeddingError

    def boom(_question, _history, _settings):
        raise EmbeddingError("embeddings request failed")

    app, store, _seen = _app(tmp_path, answer_fn=boom)
    response = TestClient(app).post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    stored = store.get_turn(response.json()["session_id"], 1)
    assert stored is not None
    assert stored.status == "unavailable"


def test_config_and_health(tmp_path) -> None:
    app, _store, _seen = _app(tmp_path)
    client = TestClient(app)
    config = client.get("/api/config")
    assert config.status_code == 200
    assert config.headers["cache-control"] == "public, max-age=60"
    payload = config.json()
    assert "AI" in payload["ai_label"]
    assert "AdaBot" in payload["opening_message"]
    assert payload["contact_url"] == ""
    assert payload["max_message_chars"] == 20
    assert "test-secret-key" not in config.text
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    down, _store2, _seen2 = _app(tmp_path, index_ok=lambda: False)
    failed = TestClient(down).get("/api/health")
    assert failed.status_code == 503
    assert failed.json() == {"status": "unavailable"}
    assert "index" not in failed.text


def test_chat_does_not_block_the_health_check(tmp_path) -> None:
    import httpx

    def slow(_question, _history, _settings):
        time.sleep(0.4)
        return _answer(_question, _history, _settings)

    app, _store, _seen = _app(tmp_path, answer_fn=slow)

    async def scenario() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            chat = asyncio.create_task(client.post("/api/chat", json={"message": "Hi"}))
            await asyncio.sleep(0.05)
            started = time.perf_counter()
            health = await client.get("/api/health")
            elapsed = time.perf_counter() - started
            await chat
            assert health.status_code == 200
            return elapsed

    elapsed = asyncio.run(scenario())
    assert elapsed < 0.3


def test_cors_star_is_rejected() -> None:
    with pytest.raises(ValueError, match="CORS_ALLOWED_ORIGINS"):
        load_settings(environ={"CORS_ALLOWED_ORIGINS": "*"})


def test_oversize_body_is_rejected(tmp_path) -> None:
    app, _store, _seen = _app(tmp_path)
    client = TestClient(app)
    blob = b'{"message":"' + (b"a" * 70000) + b'"}'
    response = client.post(
        "/api/chat",
        content=blob,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["status"] == "invalid"
