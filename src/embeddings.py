"""OpenAI-compatible embedding client with batching, retry, and truncation."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Callable

from openai import OpenAI

# nomic-embed-text on Ollama advertises a 2K context window. Empirically the two
# largest corpus chunks (~5k chars) embed successfully; we still truncate as a
# safety net. See docs/decisions/004-embed-input-limit.md.
DEFAULT_MAX_CHARS = 8000
DEFAULT_BATCH_SIZE = 32
TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class EmbedConfig:
    """Embedding endpoint and prefix settings."""

    model: str
    base_url: str
    api_key: str
    batch_size: int = DEFAULT_BATCH_SIZE
    max_chars: int = DEFAULT_MAX_CHARS
    query_prefix: str = ""
    doc_prefix: str = ""
    max_retries: int = 4
    retry_backoff_seconds: float = 0.5


def apply_prefix(text: str, prefix: str) -> str:
    """Prepend a model-specific task prefix when configured."""
    if not prefix:
        return text
    return f"{prefix}{text}"


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate to max_chars. Returns (text, was_truncated)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


class EmbeddingError(RuntimeError):
    """Raised when the embeddings API fails after retries."""


def embed_texts(
    texts: Sequence[str],
    *,
    config: EmbedConfig,
    kind: str = "document",
    client: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[list[float]], list[bool]]:
    """Embed texts. kind is 'document' or 'query' (selects prefix).

    Returns (vectors, truncated_flags) aligned with the input texts.
    """
    if kind not in {"document", "query"}:
        raise ValueError("kind must be 'document' or 'query'")
    prefix = config.doc_prefix if kind == "document" else config.query_prefix
    prepared: list[str] = []
    truncated: list[bool] = []
    for text in texts:
        prefixed = apply_prefix(text, prefix)
        clipped, was_trunc = truncate_text(prefixed, config.max_chars)
        prepared.append(clipped)
        truncated.append(was_trunc)

    if not prepared:
        return [], []

    openai_client = client or OpenAI(base_url=config.base_url, api_key=config.api_key)
    vectors: list[list[float]] = []
    batch_size = max(1, config.batch_size)
    for start in range(0, len(prepared), batch_size):
        batch = prepared[start : start + batch_size]
        vectors.extend(_embed_batch(openai_client, batch, config=config, sleep=sleep))
    return vectors, truncated


def _embed_batch(
    client: Any,
    batch: list[str],
    *,
    config: EmbedConfig,
    sleep: Callable[[float], None],
) -> list[list[float]]:
    last_error: Exception | None = None
    for attempt in range(config.max_retries + 1):
        try:
            resp = client.embeddings.create(model=config.model, input=batch)
            data = sorted(resp.data, key=lambda item: item.index)
            return [list(item.embedding) for item in data]
        except Exception as exc:  # noqa: BLE001 - narrow via status when present
            last_error = exc
            if not _is_transient(exc) or attempt >= config.max_retries:
                break
            sleep(config.retry_backoff_seconds * (2**attempt))
    raise EmbeddingError(f"embeddings request failed: {last_error}") from last_error


def _is_transient(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status in TRANSIENT_STATUS:
        return True
    name = type(exc).__name__.lower()
    return any(token in name for token in ("timeout", "connection", "rate"))
