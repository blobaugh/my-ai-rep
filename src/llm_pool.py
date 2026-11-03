"""One in-process pool for the primary and optional secondary chat connection.

The pool is the only place that decides which chat connection to call.
Embeddings never come through here. State (primary down until a timestamp)
lives in this process. A second worker has its own state.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from openai import APIConnectionError, OpenAI

from src.config import Settings

logger = logging.getLogger(__name__)

# Same-connection retries for a response that came back. Not used as failover.
# 408 is a late response from a live host, so it stays on that host.
# 429 and every 5xx fail over instead of retrying here.
_SAME_HOST_STATUS = frozenset({408})


def _status_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status in _SAME_HOST_STATUS


# A dead host should fail over in a few seconds. Generation is covered by
# the per-connection total timeout, which is much longer (see decision 016).
CONNECT_TIMEOUT_SECONDS = 5.0

T = TypeVar("T")


class ModelUnavailable(Exception):
    """Every configured chat connection failed because it was unreachable or timed out."""

    def __init__(self, message: str, *, provider_limit: bool = False) -> None:
        super().__init__(message)
        self.provider_limit = provider_limit


class _NoFailover(Exception):
    """The attempt already showed tokens, so another connection must not start over."""

    def __init__(self, original: BaseException) -> None:
        super().__init__(str(original))
        self.original = original


class LlmPool:
    """Try the primary chat connection, then the secondary when the failure qualifies."""

    def __init__(
        self,
        settings: Settings,
        *,
        clients: dict[str, Any] | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.settings = settings
        self._clients = dict(clients or {})
        self._built: dict[str, OpenAI] = {}
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._lock = threading.Lock()
        self._failover_active = False
        self._down_until: float | None = None
        if self.secondary_configured and _same_connection(settings):
            logger.warning(
                "LLM_SECONDARY_* matches the primary connection, "
                "so failover will not change hosts"
            )

    @property
    def secondary_configured(self) -> bool:
        return bool(self.settings.llm_secondary_base_url)

    @property
    def failover_active(self) -> bool:
        with self._lock:
            return self._failover_active

    def call(self, attempt: Callable[[Any, str], T]) -> tuple[T, str, bool]:
        """Run attempt(client, model). Return the value, connection name, and failover flag."""
        name, probed = self._choose()
        try:
            value = self._with_same_host_retries(attempt, name)
        except _NoFailover as exc:
            raise exc.original from exc
        except Exception as exc:
            if not failover_trigger(exc, self.settings.failover_on_http_status):
                raise
            provider_limit = _provider_limit_signal(exc)
            if provider_limit:
                logger.warning(
                    "provider limit signal: HTTP %s",
                    getattr(exc, "status_code", "?"),
                )
            if name != "primary" or not self.secondary_configured:
                raise ModelUnavailable(
                    _unavailable_message(self.secondary_configured),
                    provider_limit=provider_limit,
                ) from exc
            self._mark_down(probed=probed)
            try:
                value = self._with_same_host_retries(attempt, "secondary")
            except _NoFailover as exc2:
                raise exc2.original from exc2
            except Exception as exc2:
                limit2 = provider_limit or _provider_limit_signal(exc2)
                if limit2:
                    logger.warning(
                        "provider limit signal: HTTP %s",
                        getattr(exc2, "status_code", "?"),
                    )
                if failover_trigger(exc2, self.settings.failover_on_http_status):
                    raise ModelUnavailable(
                        _unavailable_message(self.secondary_configured),
                        provider_limit=limit2,
                    ) from exc2
                raise
            return value, "secondary", True
        if name == "primary":
            self._mark_up()
            return value, "primary", False
        return value, "secondary", True

    def _with_same_host_retries(self, attempt: Callable[[Any, str], T], name: str) -> T:
        """Retry a live host's transient HTTP status. Connection failures fail over instead."""
        delay = 0.4
        statuses = self.settings.failover_on_http_status
        for attempt_no in range(3):
            try:
                return attempt(self._client(name), self._model(name))
            except _NoFailover:
                raise
            except Exception as exc:
                if failover_trigger(exc, statuses) or not _status_retryable(exc) or attempt_no >= 2:
                    raise
                self._sleep(delay)
                delay *= 2
        raise RuntimeError("chat call failed")

    def _choose(self) -> tuple[str, bool]:
        with self._lock:
            if not self.secondary_configured or not self._failover_active:
                return "primary", False
            now = self._clock()
            if self._down_until is not None and now >= self._down_until:
                return "primary", True
            return "secondary", False

    def _mark_down(self, *, probed: bool) -> None:
        with self._lock:
            now = self._clock()
            new_until = now + self.settings.failover_retry_seconds
            already = self._failover_active
            previous_until = self._down_until
            if already and self._down_until is not None and new_until <= self._down_until:
                return
            self._down_until = new_until
            self._failover_active = True
            if not already:
                logger.warning(
                    "chat failover: primary is down; using secondary for %ss",
                    _format_seconds(self.settings.failover_retry_seconds),
                )
            elif probed and (previous_until is None or now >= previous_until):
                logger.warning(
                    "chat failover: primary still down; retry timer restarted (%ss)",
                    _format_seconds(self.settings.failover_retry_seconds),
                )

    def _mark_up(self) -> None:
        with self._lock:
            if not self._failover_active:
                return
            self._failover_active = False
            self._down_until = None
            logger.warning("chat failover: primary is active again")

    def _model(self, name: str) -> str:
        if name == "secondary":
            return self.settings.llm_secondary_model
        return self.settings.llm_model

    def _client(self, name: str) -> Any:
        if name in self._clients:
            return self._clients[name]
        built = self._built.get(name)
        if built is not None:
            return built
        if name == "secondary":
            client = build_chat_client(
                self.settings.llm_secondary_base_url,
                self.settings.llm_secondary_api_key,
                self.settings.llm_secondary_timeout_seconds,
            )
        else:
            client = build_chat_client(
                self.settings.llm_base_url,
                self.settings.llm_api_key,
                self.settings.llm_primary_timeout_seconds,
            )
        self._built[name] = client
        return client


def build_chat_client(base_url: str, api_key: str, timeout_seconds: float) -> OpenAI:
    """OpenAI client with a short connect timeout and no SDK retries.

    Retries here would hide a dead primary and delay failover.
    """
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=chat_timeout(timeout_seconds),
        max_retries=0,
    )


def chat_timeout(timeout_seconds: float) -> httpx.Timeout:
    connect = min(CONNECT_TIMEOUT_SECONDS, timeout_seconds)
    return httpx.Timeout(timeout_seconds, connect=connect)


def _provider_limit_signal(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status in (402, 429)


def failover_trigger(exc: BaseException, statuses: tuple[int, ...]) -> bool:
    """Connection failures, timeouts, HTTP 429, and any 5xx fail over.

    Other HTTP statuses stay on the host that returned them, unless listed.
    """
    if isinstance(exc, _NoFailover):
        return False
    if isinstance(
        exc,
        (APIConnectionError, httpx.TransportError, httpx.TimeoutException, TimeoutError, ConnectionError),
    ):
        return True
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        return False
    if status == 429 or 500 <= status <= 599:
        return True
    return status in statuses


def _same_connection(settings: Settings) -> bool:
    return (
        settings.llm_secondary_base_url.rstrip("/") == settings.llm_base_url.rstrip("/")
        and settings.llm_secondary_api_key == settings.llm_api_key
        and settings.llm_secondary_model == settings.llm_model
    )


def _unavailable_message(secondary_configured: bool) -> str:
    if secondary_configured:
        return "Neither chat connection is available."
    return "The chat connection is not available."


def _format_seconds(value: float) -> str:
    return format(value, "g")


_pool_lock = threading.Lock()
_pool: LlmPool | None = None
_pool_key: tuple[Any, ...] | None = None


def pool_for(settings: Settings) -> LlmPool:
    """Reuse one pool per connection config so failover state survives the next turn."""
    key = (
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        settings.llm_primary_timeout_seconds,
        settings.llm_secondary_base_url,
        settings.llm_secondary_api_key,
        settings.llm_secondary_model,
        settings.llm_secondary_timeout_seconds,
        settings.failover_retry_seconds,
        settings.failover_on_http_status,
    )
    global _pool, _pool_key
    with _pool_lock:
        if _pool is None or _pool_key != key:
            _pool = LlmPool(settings)
            _pool_key = key
        return _pool


def reset_pool() -> None:
    """Drop process state. Tests use this so one case cannot leak into the next."""
    global _pool, _pool_key
    with _pool_lock:
        _pool = None
        _pool_key = None
