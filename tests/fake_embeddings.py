"""Deterministic fake embeddings for unit tests (no Ollama)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np

from src.embeddings import EmbedConfig, apply_prefix, truncate_text
from src.vector_store import normalize_vector


def fake_embed_texts(
    texts: Sequence[str],
    *,
    config: EmbedConfig,
    kind: str = "document",
    dim: int = 16,
    **_: object,
) -> tuple[list[list[float]], list[bool]]:
    """Hash each text into a stable unit vector."""
    prefix = config.doc_prefix if kind == "document" else config.query_prefix
    vectors: list[list[float]] = []
    truncated: list[bool] = []
    for text in texts:
        prepared = apply_prefix(text, prefix)
        clipped, was_trunc = truncate_text(prepared, config.max_chars)
        truncated.append(was_trunc)
        digest = hashlib.sha256(clipped.encode("utf-8")).digest()
        # Expand digest to dim floats in a deterministic way.
        vals = []
        seed = digest
        while len(vals) < dim:
            for b in seed:
                vals.append((b / 255.0) * 2 - 1)
                if len(vals) >= dim:
                    break
            seed = hashlib.sha256(seed).digest()
        vec = normalize_vector(np.asarray(vals[:dim], dtype=np.float32))
        vectors.append(vec.tolist())
    return vectors, truncated
