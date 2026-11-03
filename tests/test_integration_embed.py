"""Optional integration test against a live Ollama embeddings endpoint."""

from __future__ import annotations

import os

import numpy as np
import pytest

from src.config import load_embed_config
from src.embeddings import embed_texts
from src.vector_store import normalize_vector

pytestmark = pytest.mark.integration


@pytest.mark.integration
def test_real_ollama_embedding_round_trip() -> None:
    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("Set RUN_INTEGRATION=1 to run live Ollama embedding tests")
    cfg = load_embed_config()
    vectors, truncated = embed_texts(
        ["BenBot integration probe"],
        config=cfg,
        kind="query",
    )
    assert truncated == [False]
    assert len(vectors) == 1
    assert len(vectors[0]) >= 8
    unit = normalize_vector(np.asarray(vectors[0], dtype=np.float32))
    assert abs(float(np.linalg.norm(unit)) - 1.0) < 1e-5
