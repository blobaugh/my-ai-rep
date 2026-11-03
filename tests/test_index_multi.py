"""Tests for multi-file chunk loading and Q&A re-embed on mode change."""

from __future__ import annotations

import json
from pathlib import Path

from src.embeddings import EmbedConfig
from src.index_chunks import build_or_update_index, load_all_chunks
from src.qa import entry_to_chunk, parse_qa
from tests.fake_embeddings import fake_embed_texts


def _cfg() -> EmbedConfig:
    return EmbedConfig(
        model="fake",
        base_url="http://example",
        api_key="x",
        query_prefix="",
        doc_prefix="",
    )


def test_load_all_chunks_and_incremental_qa(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    blog = {
        "id": "blog#0",
        "content_hash": "h-blog",
        "title": "Blog",
        "slug": "blog",
        "published_at": "2020-01-01T00:00:00Z",
        "section": "",
        "url": "https://example.com/blog",
        "source_type": "blog",
        "body": "blog body about sailing",
        "embed_text": "Blog\n\nblog body about sailing",
        "word_count": 4,
    }
    entry = parse_qa(
        "## intro\nQ: Who are you?\nA: I am Example.\nsource: x\nreview: draft\n"
    )[0]
    qa = entry_to_chunk(entry, embed_mode="question_and_answer")
    (chunks_dir / "chunks.jsonl").write_text(
        json.dumps(blog) + "\n", encoding="utf-8"
    )
    (chunks_dir / "qa_chunks.jsonl").write_text(
        json.dumps(qa) + "\n", encoding="utf-8"
    )
    loaded = load_all_chunks(chunks_dir)
    assert {c["id"] for c in loaded} == {"qa#intro"}

    index_dir = tmp_path / "index"
    r1 = build_or_update_index(
        chunks_dir=chunks_dir,
        index_dir=index_dir,
        config=_cfg(),
        embed_fn=fake_embed_texts,
        qa_embed_mode="question_and_answer",
    )
    assert r1["embedded"] == 1
    r2 = build_or_update_index(
        chunks_dir=chunks_dir,
        index_dir=index_dir,
        config=_cfg(),
        embed_fn=fake_embed_texts,
        qa_embed_mode="question_and_answer",
    )
    assert r2["embedded"] == 0
    assert r2["unchanged"] == 1

    # Edit one answer → only that Q&A row re-embeds.
    entry2 = parse_qa(
        "## intro\nQ: Who are you?\nA: I am Example updated.\n"
        "source: x\nreview: draft\n"
    )[0]
    qa2 = entry_to_chunk(entry2, embed_mode="question_and_answer")
    (chunks_dir / "qa_chunks.jsonl").write_text(
        json.dumps(qa2) + "\n", encoding="utf-8"
    )
    r3 = build_or_update_index(
        chunks_dir=chunks_dir,
        index_dir=index_dir,
        config=_cfg(),
        embed_fn=fake_embed_texts,
        qa_embed_mode="question_and_answer",
    )
    assert r3["embedded"] == 1
    assert r3["unchanged"] == 0

    # Mode change forces Q&A re-embed even if answer hash unchanged.
    r4 = build_or_update_index(
        chunks_dir=chunks_dir,
        index_dir=index_dir,
        config=_cfg(),
        embed_fn=fake_embed_texts,
        qa_embed_mode="question_only",
    )
    assert r4["embedded"] == 1
    assert r4["forced_qa_reembed"] == 1
