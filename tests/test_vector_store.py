"""Unit tests for NumpyVectorStore (fake vectors, no Ollama)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from src.vector_store import (
    NumpyVectorStore,
    VectorRecord,
    new_index_meta,
    normalize_vector,
)


def _store(dim: int = 4) -> NumpyVectorStore:
    return NumpyVectorStore(
        new_index_meta(
            embed_model="fake", dimension=dim, query_prefix="", doc_prefix=""
        )
    )


def test_normalize_vector_unit_length() -> None:
    v = normalize_vector(np.asarray([3.0, 4.0], dtype=np.float32))
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-6


def test_search_ordering() -> None:
    store = _store(2)
    store.upsert(
        [
            VectorRecord("a", [1.0, 0.0], "ha", {"slug": "a"}),
            VectorRecord("b", [0.0, 1.0], "hb", {"slug": "b"}),
            VectorRecord("c", [0.7, 0.7], "hc", {"slug": "c"}),
        ]
    )
    hits = store.search([1.0, 0.0], k=3)
    assert [h.id for h in hits] == ["a", "c", "b"]
    assert hits[0].score > hits[1].score > hits[2].score


def test_metadata_filters() -> None:
    store = _store(2)
    store.upsert(
        [
            VectorRecord(
                "old",
                [1.0, 0.0],
                "h1",
                {
                    "source_type": "blog",
                    "published_at": "2010-01-01T00:00:00Z",
                    "slug": "old",
                },
            ),
            VectorRecord(
                "new",
                [0.9, 0.1],
                "h2",
                {
                    "source_type": "blog",
                    "published_at": "2020-01-01T00:00:00Z",
                    "slug": "new",
                },
            ),
            VectorRecord(
                "qa",
                [0.8, 0.2],
                "h3",
                {
                    "source_type": "qa",
                    "published_at": "2020-01-01T00:00:00Z",
                    "slug": "qa",
                },
            ),
        ]
    )
    hits = store.search(
        [1.0, 0.0],
        k=5,
        filters={"source_type": "blog", "min_published_at": "2015-01-01"},
    )
    assert [h.id for h in hits] == ["new"]


def test_upsert_and_remove() -> None:
    store = _store(2)
    store.upsert([VectorRecord("a", [1.0, 0.0], "h1", {"slug": "a"})])
    store.upsert([VectorRecord("a", [0.0, 1.0], "h2", {"slug": "a"})])
    assert store.content_hashes()["a"] == "h2"
    hits = store.search([0.0, 1.0], k=1)
    assert hits[0].id == "a"
    store.remove(["a"])
    assert store.ids() == []
    assert store.search([0.0, 1.0], k=1) == []


def test_save_load_round_trip(tmp_path: Path) -> None:
    store = _store(3)
    store.upsert(
        [
            VectorRecord(
                "x#0",
                [1.0, 2.0, 3.0],
                "hash",
                {"slug": "x", "source_type": "blog", "title": "X"},
            )
        ]
    )
    store.save(tmp_path)
    loaded = NumpyVectorStore.load(tmp_path)
    assert loaded.ids() == ["x#0"]
    assert loaded.meta.embed_model == "fake"
    assert loaded.content_hashes()["x#0"] == "hash"
    hits = loaded.search([1.0, 2.0, 3.0], k=1)
    assert hits[0].id == "x#0"
    assert hits[0].metadata["title"] == "X"
