"""Searchable content files, with about.md kept out of the index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import load_settings, resolve_content_file
from src.index_chunks import load_all_chunks
from src.knowledge import build_content_chunks
from src.qa import expand_multi_vectors


def test_about_is_not_indexed_and_prose_and_qa_are(tmp_path: Path) -> None:
    root = tmp_path / "content"
    root.mkdir()
    (root / "about.md").write_text(
        "# About\n\nAlways on.\n\n## Extra\nPrivate detail.\n",
        encoding="utf-8",
    )
    (root / "about-ben.md").write_text("legacy biography\n", encoding="utf-8")
    (root / "hobby.md").write_text(
        "# Pottery\n\nI throw bowls on weekends.\n",
        encoding="utf-8",
    )
    notes = root / "notes"
    notes.mkdir()
    (notes / "garden.md").write_text("Tomatoes in the yard.\n", encoding="utf-8")
    (root / "qa.md").write_text(
        "## intro\n"
        "Q: Who are you? / What is your name?\n"
        "A: I am Avery.\n"
        "source: example\n"
        "review: draft\n",
        encoding="utf-8",
    )

    chunks = build_content_chunks(root, embed_mode="multi")
    blob = "\n".join(str(chunk["body"]) for chunk in chunks)
    assert "Always on" not in blob
    assert "Private detail" not in blob
    assert "legacy biography" in blob
    prose = [
        chunk
        for chunk in chunks
        if chunk["source_type"] == "prose" and "bowls" in str(chunk["body"])
    ]
    assert prose
    assert any("Tomatoes" in str(chunk["body"]) for chunk in chunks)

    qa_rows = [chunk for chunk in chunks if chunk["source_type"] == "qa"]
    assert [chunk["slug"] for chunk in qa_rows] == ["intro"]
    expanded = expand_multi_vectors(qa_rows, q_embed_kind="document")
    question_vectors = [row["embed_text"] for row in expanded if row.get("kind") == "q"]
    assert "Who are you?" in question_vectors
    assert "What is your name?" in question_vectors
    assert any(row.get("kind") == "qa" and "Avery" in row["embed_text"] for row in expanded)


def test_chunks_jsonl_is_not_an_index_input(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    leftover = {
        "id": "blog#only-here",
        "content_hash": "h",
        "title": "Old post",
        "slug": "old-post",
        "body": "This row exists only in the leftover file.",
        "embed_text": "leftover",
        "source_type": "blog",
    }
    kept = {
        "id": "prose#hobby#0",
        "content_hash": "h2",
        "title": "Pottery",
        "slug": "hobby-0",
        "body": "I throw bowls on weekends.",
        "embed_text": "Pottery",
        "source_type": "prose",
    }
    (chunks_dir / "chunks.jsonl").write_text(
        json.dumps(leftover) + "\n", encoding="utf-8"
    )
    (chunks_dir / "knowledge.jsonl").write_text(
        json.dumps(kept) + "\n", encoding="utf-8"
    )
    loaded = load_all_chunks(chunks_dir)
    assert [chunk["id"] for chunk in loaded] == ["prose#hobby#0"]


def test_missing_about_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "about-ben.md").write_text("legacy\n", encoding="utf-8")
    monkeypatch.setattr("src.config._ROOT", tmp_path)
    settings = load_settings(environ={"CONTENT_DIR": "pack"})
    found = resolve_content_file("about", settings)
    assert found.name == "about.md"
    assert not found.is_file()
