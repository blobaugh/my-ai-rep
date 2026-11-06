"""FastAPI application. The proxy is not asked to rewrite /api."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import APIConnectionError, APITimeoutError
from starlette.concurrency import run_in_threadpool

from src.api.copy import (
    BAD_REQUEST,
    BUSY,
    EMPTY_MESSAGE,
    ERROR_TEXT,
    SESSION_FULL,
    TOO_LARGE,
    TOO_LONG,
    UNAVAILABLE,
    daily_limit_message,
    public_config,
    strip_controls,
)
from src.api.limits import TurnSlots
from src.config import Settings
from src.embeddings import EmbeddingError
from src.health import INDEX_DIR
from src.llm_pool import ModelUnavailable
from src.pipeline import Answer, answer_turn
from src.store import Store

logger = logging.getLogger("src.api")

AnswerFn = Callable[..., Answer]


def create_app(
    *,
    settings: Settings,
    store: Store,
    answer_fn: AnswerFn | None = None,
    index_ok: Callable[[], bool] | None = None,
) -> FastAPI:
    """Build the app. Tests pass a fake ``answer_fn`` and a temp store."""
    complete = answer_fn or answer_turn
    ready = index_ok or _index_files_ok
    slots = TurnSlots(settings)
    api_title = settings.bot_name.strip() or "Chat API"
    app = FastAPI(title=api_title, docs_url=None, redoc_url=None, openapi_url=None)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allowed_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["content-type"],
        )

    @app.middleware("http")
    async def request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = uuid.uuid4().hex
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            return _body("error", BAD_REQUEST, None, None, exc.status_code)
        logger.error(
            "%s",
            _log_line(getattr(request.state, "request_id", ""), "error", 500),
        )
        logger.debug("unhandled %s", type(exc).__name__)
        return _body("error", ERROR_TEXT, None, None, 500)

    @app.get("/api/config")
    def get_config() -> JSONResponse:
        return JSONResponse(
            public_config(settings),
            headers={"cache-control": "public, max-age=60"},
        )

    @app.get("/api/health")
    def get_health() -> JSONResponse:
        if ready() and _database_ok(store):
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.post("/api/chat")
    async def post_chat(request: Request) -> JSONResponse:
        request_id = str(getattr(request.state, "request_id", ""))
        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("application/json"):
            return _logged(request_id, "invalid", 400, BAD_REQUEST, None, None)
        limit = _body_limit(settings)
        advertised = request.headers.get("content-length", "")
        if advertised.isdigit() and int(advertised) > limit:
            return _logged(request_id, "invalid", 400, TOO_LARGE, None, None)
        raw = await request.body()
        if len(raw) > limit:
            return _logged(request_id, "invalid", 400, TOO_LARGE, None, None)
        payload = _object(raw)
        if payload is None:
            return _logged(request_id, "invalid", 400, BAD_REQUEST, None, None)
        message = payload.get("message")
        if not isinstance(message, str):
            return _logged(request_id, "invalid", 400, BAD_REQUEST, None, None)
        cleaned = strip_controls(message)
        if not cleaned.strip():
            return _logged(request_id, "invalid", 400, EMPTY_MESSAGE, None, None)
        if len(cleaned) > settings.message_max_chars:
            return _logged(request_id, "invalid", 400, TOO_LONG, None, None)
        gate = slots.admission(store)
        if gate == "daily_limit":
            return _chat_response(
                request_id,
                "daily_limit",
                429,
                daily_limit_message(settings),
                None,
                None,
            )
        if not slots.acquire():
            return _chat_response(request_id, "busy", 429, BUSY, None, None)

        try:
            supplied = payload.get("session_id")
            client_id = supplied if isinstance(supplied, str) else None
            resolution = store.resolve_session(client_id)
            session_id = resolution.session_id
            if resolution.state == "full":
                store.begin_turn(session_id, cleaned, full_reply=SESSION_FULL)
                used = store.message_count(session_id)
                return _chat_response(
                    request_id,
                    "session_full",
                    409,
                    SESSION_FULL,
                    session_id,
                    _usage(used, settings.session_max_messages),
                    category="session_full",
                )

            history = store.history(session_id, settings.history_turns)
            pending = store.begin_turn(session_id, cleaned)
            try:
                answer = await run_in_threadpool(
                    lambda: complete(cleaned, history, settings)
                )
            except ModelUnavailable as exc:
                flags = ("provider_limit",) if exc.provider_limit else ()
                store.finish_turn(
                    session_id,
                    pending.sequence,
                    reply=UNAVAILABLE,
                    status="unavailable",
                    category="unavailable",
                    flags=flags,
                )
                used = store.message_count(session_id)
                return _chat_response(
                    request_id,
                    "unavailable",
                    503,
                    UNAVAILABLE,
                    session_id,
                    _usage(used, settings.session_max_messages),
                    category="unavailable",
                )
            except (APIConnectionError, APITimeoutError, EmbeddingError, OSError):
                store.finish_turn(
                    session_id,
                    pending.sequence,
                    reply=UNAVAILABLE,
                    status="unavailable",
                    category="unavailable",
                )
                used = store.message_count(session_id)
                return _chat_response(
                    request_id,
                    "unavailable",
                    503,
                    UNAVAILABLE,
                    session_id,
                    _usage(used, settings.session_max_messages),
                    category="unavailable",
                )
            except Exception:  # noqa: BLE001
                logger.error("%s", _log_line(request_id, "error", 500))
                store.finish_turn(
                    session_id,
                    pending.sequence,
                    reply=ERROR_TEXT,
                    status="error",
                    category="error",
                )
                used = store.message_count(session_id)
                return _chat_response(
                    request_id,
                    "error",
                    500,
                    ERROR_TEXT,
                    session_id,
                    _usage(used, settings.session_max_messages),
                    category="error",
                )

            _save_answer(store, settings, session_id, pending.sequence, answer)
            used = store.message_count(session_id)
            category = (
                answer.outcome.category if answer.outcome is not None else None
            )
            return _chat_response(
                request_id,
                "ok",
                200,
                answer.text,
                session_id,
                _usage(used, settings.session_max_messages),
                category=category,
            )
        finally:
            slots.release()

    return app


def _save_answer(
    store: Store,
    settings: Settings,
    session_id: str,
    sequence: int,
    answer: Answer,
) -> None:
    outcome = answer.outcome
    debug = answer.debug
    retrieved = _retrieved(debug)
    connection = debug.get("connection_used")
    if connection == "secondary" and settings.llm_secondary_model:
        chat_model = settings.llm_secondary_model
    else:
        chat_model = settings.llm_model
    timings = outcome.timings_ms if outcome is not None else None
    tokens = outcome.prompt_tokens if outcome is not None else None
    category = outcome.category if outcome is not None else debug.get("category")
    flags = list(outcome.flags if outcome is not None else ())
    if debug.get("provider_limit"):
        flags.append("provider_limit")
    top_score = outcome.top_score if outcome is not None else debug.get("top_score")
    if not isinstance(top_score, (int, float)):
        top_score = None
    failover = debug.get("failover_active")
    store.finish_turn(
        session_id,
        sequence,
        reply=answer.text,
        status="ok",
        category=None if category is None else str(category),
        flags=tuple(str(flag) for flag in dict.fromkeys(flags)),
        top_score=None if top_score is None else float(top_score),
        retrieved=retrieved,
        repair=None if debug.get("repair") is None else str(debug.get("repair")),
        connection_used=None if connection is None else str(connection),
        failover_active=None if failover is None else bool(failover),
        models={"chat": chat_model, "embed": settings.embed_model},
        finish_reason=answer.finish_reason,
        timings=timings,
        prompt_tokens=tokens,
    )


def _retrieved(debug: dict[str, Any]) -> list[dict[str, Any]]:
    rows = debug.get("retrieved") or []
    if not isinstance(rows, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = row.get("score")
        cleaned.append(
            {
                "id": str(row.get("id") or ""),
                "score": float(score) if isinstance(score, (int, float)) else 0.0,
            }
        )
    return cleaned


def _object(raw: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _usage(used: int, maximum: int) -> dict[str, int]:
    return {"messages_used": used, "messages_max": maximum}


def _body_limit(_settings: Settings) -> int:
    return 8192


def _index_files_ok() -> bool:
    return (INDEX_DIR / "index.json").is_file() and (INDEX_DIR / "vectors.npy").is_file()


def _database_ok(store: Store) -> bool:
    try:
        conn = sqlite3.connect(store.path, timeout=1)
    except sqlite3.Error:
        return False
    try:
        conn.execute("SELECT 1 FROM sessions LIMIT 1")
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _logged(
    request_id: str,
    status: str,
    http_status: int,
    reply: str,
    session_id: str | None,
    usage: dict[str, int] | None,
    *,
    category: str | None = None,
) -> JSONResponse:
    logger.info("%s", _log_line(request_id, status, http_status, category))
    return _body(status, reply, session_id, usage, http_status)


def _chat_response(
    request_id: str,
    status: str,
    http_status: int,
    reply: str,
    session_id: str | None,
    usage: dict[str, int] | None,
    *,
    category: str | None = None,
) -> JSONResponse:
    logger.info("%s", _log_line(request_id, status, http_status, category))
    return _body(
        status,
        reply,
        session_id,
        usage,
        http_status,
        extra_headers={"Cache-Control": "no-store"},
    )


def _body(
    status: str,
    reply: str,
    session_id: str | None,
    usage: dict[str, int] | None,
    http_status: int,
    *,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    headers = dict(extra_headers or {})
    return JSONResponse(
        {
            "session_id": session_id,
            "reply": reply,
            "status": status,
            "session": usage,
        },
        status_code=http_status,
        headers=headers,
    )


def _log_line(
    request_id: str,
    status: str,
    http_status: int,
    category: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "request_id": request_id,
        "status": status,
        "http": http_status,
    }
    if category:
        payload["category"] = category
    return json.dumps(payload, ensure_ascii=True)
