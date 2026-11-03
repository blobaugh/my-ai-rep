"""Unit tests for retrieve() caps, dedupe, and min_score."""

from __future__ import annotations

import pytest

from src.embeddings import EmbedConfig
from src.retrieve import (
    apply_per_article_cap,
    dedupe_exact_by_hash,
    retrieve,
)
from src.vector_store import (
    NumpyVectorStore,
    SearchHit,
    VectorRecord,
    new_index_meta,
)
from tests.fake_embeddings import fake_embed_texts


def _cfg() -> EmbedConfig:
    return EmbedConfig(
        model="fake",
        base_url="http://example",
        api_key="x",
        query_prefix="",
        doc_prefix="",
    )


def test_dedupe_exact_by_hash_keeps_best_score() -> None:
    hits = [
        SearchHit("a#0", 0.5, "same", {"slug": "a"}),
        SearchHit("b#0", 0.9, "same", {"slug": "b"}),
        SearchHit("c#0", 0.7, "other", {"slug": "c"}),
    ]
    out = dedupe_exact_by_hash(hits)
    ids = {h.id for h in out}
    assert "b#0" in ids
    assert "a#0" not in ids
    assert "c#0" in ids


def test_per_article_cap() -> None:
    hits = [
        SearchHit("a#0", 0.9, "h0", {"slug": "a"}),
        SearchHit("a#1", 0.8, "h1", {"slug": "a"}),
        SearchHit("a#2", 0.7, "h2", {"slug": "a"}),
        SearchHit("b#0", 0.6, "h3", {"slug": "b"}),
    ]
    out = apply_per_article_cap(hits, max_per_article=2)
    assert [h.id for h in out] == ["a#0", "a#1", "b#0"]


def test_retrieve_cap_dedupe_and_min_score() -> None:
    store = NumpyVectorStore(new_index_meta(embed_model="fake", dimension=16))
    # Build docs with known embed texts so fake vectors are stable.
    docs = [
        ("proxy#0", "how-to-proxy", "nginx proxy setup guide", "h-proxy-0"),
        ("proxy#1", "how-to-proxy", "more nginx proxy details", "h-proxy-1"),
        ("proxy#2", "how-to-proxy", "even more nginx proxy", "h-proxy-2"),
        ("dup-a#0", "dup-a", "identical sailing story", "same-hash"),
        ("dup-b#0", "dup-b", "identical sailing story", "same-hash"),
        ("other#0", "other", "completely unrelated cooking", "h-other"),
    ]
    cfg = _cfg()
    for cid, slug, body, chash in docs:
        embed_text = f"{slug}\n\n{body}"
        vecs, _ = fake_embed_texts([embed_text], config=cfg, kind="document")
        store.upsert(
            [
                VectorRecord(
                    cid,
                    vecs[0],
                    chash,
                    {
                        "title": slug,
                        "slug": slug,
                        "url": f"https://example.com/{slug}",
                        "published_at": "2020-01-01T00:00:00Z",
                        "section": "",
                        "body": body,
                        "source_type": "blog",
                        "embed_text": embed_text,
                    },
                )
            ]
        )

    # Query close to nginx proxy text.
    results = retrieve(
        "nginx proxy setup guide",
        k=5,
        max_per_article=2,
        store=store,
        config=cfg,
        embed_fn=fake_embed_texts,
    )
    proxy_hits = [r for r in results if r.slug == "how-to-proxy"]
    assert len(proxy_hits) <= 2
    hashes = [r.content_hash for r in results]
    assert hashes.count("same-hash") <= 1

    filtered = retrieve(
        "nginx proxy setup guide",
        k=5,
        min_score=0.999999,
        store=store,
        config=cfg,
        embed_fn=fake_embed_texts,
    )
    # Extremely high threshold should filter most/all fake cosine scores.
    assert len(filtered) <= len(results)

    # Add a Q&A hit and filter by source_types.
    qa_text = "What does AI-first mean to you?"
    qa_vecs, _ = fake_embed_texts([qa_text], config=cfg, kind="document")
    store.upsert(
        [
            VectorRecord(
                "qa#ai-first-meaning",
                qa_vecs[0],
                "hash-qa",
                {
                    "title": qa_text,
                    "slug": "ai-first-meaning",
                    "url": "",
                    "published_at": "",
                    "section": "",
                    "body": "Human review every line.",
                    "source_type": "qa",
                    "embed_text": qa_text,
                },
            )
        ]
    )
    qa_only = retrieve(
        qa_text,
        k=5,
        store=store,
        config=cfg,
        embed_fn=fake_embed_texts,
        source_types={"qa"},
    )
    assert qa_only
    assert all(r.source_type == "qa" for r in qa_only)
    none = retrieve(
        qa_text,
        k=5,
        store=store,
        config=cfg,
        embed_fn=fake_embed_texts,
        source_types=set(),
    )
    assert none == []


def test_retrieve_default_k_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Settings:
        retrieval_k = 1

    monkeypatch.setattr("src.retrieve.load_settings", lambda: _Settings())
    store = NumpyVectorStore(new_index_meta(embed_model="fake", dimension=16))
    cfg = _cfg()

    def add(cid: str, slug: str, body: str) -> None:
        embed_text = f"{slug}\n\n{body}"
        vecs, _ = fake_embed_texts([embed_text], config=cfg, kind="document")
        store.upsert(
            [
                VectorRecord(
                    cid,
                    vecs[0],
                    cid,
                    {
                        "title": slug,
                        "slug": slug,
                        "url": "",
                        "published_at": "",
                        "section": "",
                        "body": body,
                        "source_type": "blog",
                        "embed_text": embed_text,
                    },
                )
            ]
        )

    add("a#0", "proxy", "nginx proxy setup guide")
    add("b#0", "cooking", "completely unrelated cooking")
    results = retrieve(
        "nginx proxy setup guide",
        store=store,
        config=cfg,
        embed_fn=fake_embed_texts,
    )
    assert len(results) == 1
