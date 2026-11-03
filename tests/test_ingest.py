"""Manual ingest: validation, incremental embed, and atomic index swap."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from src.api.app import create_app
from src.config import load_settings
from src.embeddings import EmbedConfig
from src.index_chunks import IndexCompatibilityError
from src.ingest import run_ingest
from src.knowledge import ContentValidationError
from src.retrieve import load_index, retrieve
from src.store import Store
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


def _content_tree(root: Path) -> None:
    root.mkdir()
    (root / "about.md").write_text("# About\n\nPrompt only.\n", encoding="utf-8")
    (root / "note.md").write_text("# Note\n\nAlpha body.\n", encoding="utf-8")


def test_second_run_embeds_nothing(tmp_path: Path) -> None:
    content = tmp_path / "content"
    data = tmp_path / "data"
    index_dir = data / "index"
    chunks_path = data / "chunks" / "knowledge.jsonl"
    _content_tree(content)
    report1 = run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
    )
    assert report1["embedded"] == 1
    report2 = run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
    )
    assert report2["embedded"] == 0
    assert report2["unchanged"] == 1


def test_one_changed_passage_reembeds_only_that(tmp_path: Path) -> None:
    content = tmp_path / "content"
    data = tmp_path / "data"
    index_dir = data / "index"
    chunks_path = data / "chunks" / "knowledge.jsonl"
    _content_tree(content)
    run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
    )
    (content / "note.md").write_text("# Note\n\nBeta body.\n", encoding="utf-8")
    report = run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
    )
    assert report["embedded"] == 1
    assert report["unchanged"] == 0


def test_malformed_qa_leaves_old_index(tmp_path: Path) -> None:
    content = tmp_path / "content"
    data = tmp_path / "data"
    index_dir = data / "index"
    chunks_path = data / "chunks" / "knowledge.jsonl"
    _content_tree(content)
    run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
    )
    before = (index_dir / "index.json").read_text(encoding="utf-8")
    (content / "bad.md").write_text(
        "## dup\n"
        "Q: First?\n"
        "A: One.\n"
        "source: example\n"
        "review: draft\n\n"
        "## dup\n"
        "Q: Second?\n"
        "A: Two.\n"
        "source: example\n"
        "review: draft\n",
        encoding="utf-8",
    )
    with pytest.raises(ContentValidationError) as exc:
        run_ingest(
            content_dir=content,
            index_dir=index_dir,
            chunks_path=chunks_path,
            embed_fn=fake_embed_texts,
        )
    assert exc.value.line is not None
    assert (index_dir / "index.json").read_text(encoding="utf-8") == before


def test_prose_without_qa_lines_indexes(tmp_path: Path) -> None:
    content = tmp_path / "content"
    data = tmp_path / "data"
    index_dir = data / "index"
    chunks_path = data / "chunks" / "knowledge.jsonl"
    _content_tree(content)
    (content / "plain.md").write_text("Just a note without Q or A lines.\n", encoding="utf-8")
    report = run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
    )
    assert report["total_indexed"] == 2


def test_embed_failure_leaves_old_index(tmp_path: Path) -> None:
    content = tmp_path / "content"
    data = tmp_path / "data"
    index_dir = data / "index"
    chunks_path = data / "chunks" / "knowledge.jsonl"
    _content_tree(content)
    run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
    )
    before = (index_dir / "index.json").read_text(encoding="utf-8")
    (content / "note.md").write_text("# Note\n\nChanged.\n", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise RuntimeError("embed failed")

    with pytest.raises(RuntimeError, match="embed failed"):
        run_ingest(
            content_dir=content,
            index_dir=index_dir,
            chunks_path=chunks_path,
            embed_fn=boom,
        )
    assert (index_dir / "index.json").read_text(encoding="utf-8") == before


def test_model_change_refused(tmp_path: Path) -> None:
    content = tmp_path / "content"
    data = tmp_path / "data"
    index_dir = data / "index"
    chunks_path = data / "chunks" / "knowledge.jsonl"
    _content_tree(content)

    run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
        config=_cfg(model="fake-a"),
    )

    with pytest.raises(IndexCompatibilityError):
        run_ingest(
            content_dir=content,
            index_dir=index_dir,
            chunks_path=chunks_path,
            embed_fn=fake_embed_texts,
            config=_cfg(model="fake-b"),
        )


def test_check_makes_no_embedding_calls(tmp_path: Path) -> None:
    content = tmp_path / "content"
    _content_tree(content)

    def boom(*_args, **_kwargs):
        raise AssertionError("embed must not run in --check")

    report = run_ingest(
        content_dir=content,
        index_dir=tmp_path / "index",
        chunks_path=tmp_path / "chunks" / "knowledge.jsonl",
        check_only=True,
        embed_fn=boom,
    )
    assert report["check_only"] is True
    assert not (tmp_path / "index" / "index.json").exists()


def test_swap_visible_to_retrieve(tmp_path: Path) -> None:
    content = tmp_path / "content"
    data = tmp_path / "data"
    index_dir = data / "index"
    chunks_path = data / "chunks" / "knowledge.jsonl"
    _content_tree(content)
    run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
    )
    hits_before = retrieve("Alpha", index_dir=index_dir, embed_fn=fake_embed_texts)
    assert hits_before and "Alpha" in hits_before[0].body

    (content / "note.md").write_text("# Note\n\nOmega body.\n", encoding="utf-8")
    run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
    )
    load_index(index_dir)
    hits_after = retrieve("Omega", index_dir=index_dir, embed_fn=fake_embed_texts)
    assert hits_after and "Omega" in hits_after[0].body


def test_api_health_during_ingest_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = tmp_path / "content"
    data = tmp_path / "data"
    index_dir = data / "index"
    chunks_path = data / "chunks" / "knowledge.jsonl"
    db = data / "benbot.sqlite"
    _content_tree(content)
    run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
        config=_cfg(),
    )

    settings = load_settings(
        environ={
            "CONTENT_DIR": str(content),
            "DB_PATH": str(db),
            "QA_EMBED_MODE": "question_and_answer",
        }
    )
    store = Store(
        db,
        idle_minutes=settings.session_idle_minutes,
        max_messages=settings.session_max_messages,
    )
    monkeypatch.chdir(tmp_path)
    index_ok = lambda: (index_dir / "index.json").is_file() and (
        index_dir / "vectors.npy"
    ).is_file()
    app = create_app(settings=settings, store=store, index_ok=index_ok)
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200

    (content / "note.md").write_text("# Note\n\nSwapped text.\n", encoding="utf-8")
    run_ingest(
        content_dir=content,
        index_dir=index_dir,
        chunks_path=chunks_path,
        embed_fn=fake_embed_texts,
        config=_cfg(),
    )
    assert client.get("/api/health").status_code == 200
    hits = retrieve(
        "Swapped",
        index_dir=index_dir,
        embed_fn=fake_embed_texts,
        config=_cfg(),
    )
    assert hits and "Swapped" in hits[0].body
