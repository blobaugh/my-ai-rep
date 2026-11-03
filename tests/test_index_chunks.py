"""Unit tests for incremental indexing (fake embeddings)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.embeddings import EmbedConfig
from src.index_chunks import (
    IndexCompatibilityError,
    build_or_update_index,
    plan_updates,
)
from src.vector_store import NumpyVectorStore
from tests.fake_embeddings import fake_embed_texts


def _cfg(**kwargs: object) -> EmbedConfig:
    base = {
        "model": "fake-embed",
        "base_url": "http://example",
        "api_key": "x",
        "batch_size": 8,
        "max_chars": 1000,
        "query_prefix": "",
        "doc_prefix": "",
    }
    base.update(kwargs)
    return EmbedConfig(**base)  # type: ignore[arg-type]


def _write_chunks(path: Path, chunks: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(c, sort_keys=True) for c in chunks) + "\n",
        encoding="utf-8",
    )


def _chunk(
    cid: str,
    body: str,
    *,
    slug: str | None = None,
    content_hash: str | None = None,
) -> dict:
    slug = slug or cid.split("#")[0]
    return {
        "id": cid,
        "content_hash": content_hash or f"hash-{cid}-{body}",
        "title": slug,
        "slug": slug,
        "published_at": "2020-01-01T00:00:00.000Z",
        "section": "",
        "url": f"https://example.com/blog/{slug}",
        "source_type": "blog",
        "body": body,
        "embed_text": f"{slug}\n\n{body}",
        "word_count": len(body.split()),
    }


def test_plan_updates_changed_hash_detection() -> None:
    chunks = [_chunk("a#0", "one"), _chunk("b#0", "two")]
    existing = {"a#0": chunks[0]["content_hash"], "c#0": "gone"}
    to_embed, unchanged, remove = plan_updates(chunks, existing)
    assert [c["id"] for c in to_embed] == ["b#0"]
    assert unchanged == ["a#0"]
    assert remove == ["c#0"]


def test_incremental_embed_only_changed(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    chunks = [_chunk("a#0", "alpha"), _chunk("b#0", "beta")]
    _write_chunks(chunks_path, chunks)

    report1 = build_or_update_index(
        chunks_path=chunks_path,
        index_dir=index_dir,
        config=_cfg(),
        embed_fn=fake_embed_texts,
    )
    assert report1["embedded"] == 2
    assert report1["unchanged"] == 0

    report2 = build_or_update_index(
        chunks_path=chunks_path,
        index_dir=index_dir,
        config=_cfg(),
        embed_fn=fake_embed_texts,
    )
    assert report2["embedded"] == 0
    assert report2["unchanged"] == 2

    chunks[1] = _chunk("b#0", "beta-changed")
    _write_chunks(chunks_path, chunks)
    report3 = build_or_update_index(
        chunks_path=chunks_path,
        index_dir=index_dir,
        config=_cfg(),
        embed_fn=fake_embed_texts,
    )
    assert report3["embedded"] == 1
    assert report3["unchanged"] == 1


def test_model_change_requires_rebuild(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, [_chunk("a#0", "alpha")])
    build_or_update_index(
        chunks_path=chunks_path,
        index_dir=index_dir,
        config=_cfg(model="fake-a"),
        embed_fn=fake_embed_texts,
    )
    with pytest.raises(IndexCompatibilityError):
        build_or_update_index(
            chunks_path=chunks_path,
            index_dir=index_dir,
            config=_cfg(model="fake-b"),
            embed_fn=fake_embed_texts,
        )


def test_prefix_change_requires_rebuild(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    _write_chunks(chunks_path, [_chunk("a#0", "alpha")])
    build_or_update_index(
        chunks_path=chunks_path,
        index_dir=index_dir,
        config=_cfg(doc_prefix=""),
        embed_fn=fake_embed_texts,
    )
    with pytest.raises(IndexCompatibilityError):
        build_or_update_index(
            chunks_path=chunks_path,
            index_dir=index_dir,
            config=_cfg(doc_prefix="search_document: "),
            embed_fn=fake_embed_texts,
        )


def test_truncation_logged(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    index_dir = tmp_path / "index"
    big = "x" * 50
    _write_chunks(chunks_path, [_chunk("big#0", big)])
    report = build_or_update_index(
        chunks_path=chunks_path,
        index_dir=index_dir,
        config=_cfg(max_chars=10),
        embed_fn=fake_embed_texts,
    )
    assert report["truncated_ids"] == ["big#0"]
    store = NumpyVectorStore.load(index_dir)
    assert store.ids() == ["big#0"]
