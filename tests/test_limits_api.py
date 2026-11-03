"""Concurrency, daily cap, and hardening on the HTTP API."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import httpx
from starlette.testclient import TestClient

from src.api.app import create_app
from src.api.copy import BUSY
from src.store import Store
from tests.test_api import _answer, _settings


def _app(tmp_path, *, clock=None, **settings_overrides):
    settings = _settings(**settings_overrides)
    moment = clock or (lambda: datetime(2026, 11, 3, 15, tzinfo=timezone.utc))
    store = Store(
        tmp_path / "limits.sqlite",
        idle_minutes=settings.session_idle_minutes,
        max_messages=settings.session_max_messages,
        clock=moment,
    )

    def slow(_question, _history, _settings):
        time.sleep(0.35)
        return _answer(_question, _history, _settings)

    app = create_app(settings=settings, store=store, answer_fn=slow, index_ok=lambda: True)
    return app, store, settings


def test_busy_when_concurrency_exhausted(tmp_path) -> None:
    app, _store, _settings = _app(tmp_path, MAX_CONCURRENT_TURNS="1", BUSY_WAIT_SECONDS="1")
    transport = httpx.ASGITransport(app=app)

    async def run_pair() -> tuple[int, httpx.Response]:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(
                client.post("/api/chat", json={"message": "one"}, headers={"content-type": "application/json"})
            )
            await asyncio.sleep(0.05)
            second = await client.post(
                "/api/chat",
                json={"message": "two"},
                headers={"content-type": "application/json"},
            )
            r1 = await first
            return r1.status_code, second

    first_status, second = asyncio.run(run_pair())
    assert first_status == 200
    assert second.status_code == 429
    assert second.json()["status"] == "busy"
    assert second.json()["reply"] == BUSY


def test_daily_cap_persists_in_sqlite(tmp_path) -> None:
    clock = {"now": datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)}
    settings = _settings(DAILY_MESSAGE_CAP="2", MAX_CONCURRENT_TURNS="0")
    store = Store(
        tmp_path / "daily.sqlite",
        idle_minutes=60,
        max_messages=50,
        clock=lambda: clock["now"],
    )
    app = create_app(settings=settings, store=store, answer_fn=_answer, index_ok=lambda: True)
    client = TestClient(app)
    headers = {"content-type": "application/json"}
    assert client.post("/api/chat", json={"message": "a"}, headers=headers).status_code == 200
    assert client.post("/api/chat", json={"message": "b"}, headers=headers).status_code == 200
    third = client.post("/api/chat", json={"message": "c"}, headers=headers)
    assert third.status_code == 429
    assert third.json()["status"] == "daily_limit"
    store2 = Store(
        tmp_path / "daily.sqlite",
        idle_minutes=60,
        max_messages=50,
        clock=lambda: clock["now"],
    )
    again = TestClient(create_app(settings=settings, store=store2, answer_fn=_answer, index_ok=lambda: True))
    blocked = again.post("/api/chat", json={"message": "d"}, headers=headers)
    assert blocked.status_code == 429
    from datetime import timedelta

    clock["now"] = clock["now"] + timedelta(days=1)
    fresh = again.post("/api/chat", json={"message": "e"}, headers=headers)
    assert fresh.status_code == 200


def test_json_content_type_required(tmp_path) -> None:
    app, _store, _settings = _app(tmp_path)
    client = TestClient(app)
    response = client.post("/api/chat", content=b'{"message":"hi"}', headers={"content-type": "text/plain"})
    assert response.status_code == 400


def test_chat_has_no_store_header(tmp_path) -> None:
    app, _store, _settings = _app(tmp_path, MAX_CONCURRENT_TURNS="0")
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"message": "hi"},
        headers={"content-type": "application/json"},
    )
    assert response.headers.get("cache-control") == "no-store"
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_log_line_is_json_without_visitor_text(tmp_path, caplog) -> None:
    caplog.set_level("INFO", logger="src.api")
    app, _store, _settings = _app(tmp_path, MAX_CONCURRENT_TURNS="0")
    client = TestClient(app)
    message = "hello\n\"request_id\": \"forged\""
    client.post(
        "/api/chat",
        json={"message": message},
        headers={"content-type": "application/json"},
    )
    records = [record.getMessage() for record in caplog.records if "request_id" in record.getMessage()]
    assert records
    parsed = json.loads(records[-1])
    assert "forged" not in records[-1] or parsed.get("request_id") != "forged"
    assert "hello" not in records[-1]


def test_message_length_boundary(tmp_path) -> None:
    settings = _settings(MESSAGE_MAX_CHARS="5", MAX_CONCURRENT_TURNS="0")
    store = Store(tmp_path / "bound.sqlite", max_messages=50)
    app = create_app(settings=settings, store=store, answer_fn=_answer, index_ok=lambda: True)
    client = TestClient(app)
    headers = {"content-type": "application/json"}
    ok = client.post("/api/chat", json={"message": "12345"}, headers=headers)
    assert ok.status_code == 200
    bad = client.post("/api/chat", json={"message": "123456"}, headers=headers)
    assert bad.status_code == 400
