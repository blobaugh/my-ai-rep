"""Tests for markdown chunking (written first for BENBOT-4)."""

from __future__ import annotations

from pathlib import Path

from src.chunk_articles import parse_front_matter
from src.chunking import ChunkConfig, chunk_markdown, word_count

FIXTURES = Path(__file__).parent / "fixtures"

DEFAULT = ChunkConfig(
    target_words=300,
    max_words=450,
    min_words=60,
    overlap_words=40,
    blog_base_url="https://example.com/blog/",
)


def _chunk(
    body: str,
    *,
    title: str = "Title",
    slug: str = "slug",
    published_at: str = "2020-01-01T00:00:00.000Z",
    config: ChunkConfig = DEFAULT,
):
    return chunk_markdown(
        body,
        title=title,
        slug=slug,
        published_at=published_at,
        config=config,
    )


def test_short_post_is_one_chunk() -> None:
    text = (FIXTURES / "anchored_in_silence.md").read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    chunks = _chunk(
        body,
        title=meta["title"],
        slug=meta["slug"],
        published_at=meta["published_at"],
    )
    assert len(chunks) == 1
    assert chunks[0].id == f"{meta['slug']}#0"
    assert chunks[0].word_count == word_count(body)
    assert chunks[0].word_count < DEFAULT.target_words


def test_heading_boundaries_respected() -> None:
    body = "## Alpha\n\n" + ("word " * 80) + "\n\n## Beta\n\n" + ("word " * 80)
    # Force sections not to merge: each section ~80 words >= min 60, under max
    config = ChunkConfig(
        target_words=100,
        max_words=120,
        min_words=60,
        overlap_words=20,
        blog_base_url="https://example.com/blog/",
    )
    chunks = _chunk(body, config=config)
    assert len(chunks) >= 2
    assert any(c.section == "Alpha" for c in chunks)
    assert any(c.section == "Beta" for c in chunks)
    # No chunk should mix both headings
    for c in chunks:
        assert not ("## Alpha" in c.body and "## Beta" in c.body)


def test_long_section_splits_at_paragraphs_with_overlap() -> None:
    paras = [" ".join([f"p{n}w{i}" for i in range(80)]) for n in range(4)]
    body = "## Long\n\n" + "\n\n".join(paras)
    config = ChunkConfig(
        target_words=100,
        max_words=120,
        min_words=40,
        overlap_words=30,
        blog_base_url="https://example.com/blog/",
    )
    chunks = _chunk(body, config=config)
    assert len(chunks) >= 2
    assert all(c.section == "Long" for c in chunks)
    # Following chunks start with overlap from previous
    for prev, cur in zip(chunks, chunks[1:]):
        prev_tail = " ".join(prev.body.split()[-config.overlap_words :])
        # At least some overlap words appear at the start of the next chunk
        overlap_hits = sum(1 for w in prev_tail.split()[:10] if w in cur.body[:400])
        assert overlap_hits >= 3


def test_oversize_paragraph_splits_at_sentences() -> None:
    sentences = [
        f"Sentence number {i} continues with filler words here." for i in range(40)
    ]
    body = " ".join(sentences)
    config = ChunkConfig(
        target_words=80,
        max_words=100,
        min_words=20,
        overlap_words=20,
        blog_base_url="https://example.com/blog/",
    )
    chunks = _chunk(body, config=config)
    assert len(chunks) >= 2
    assert all(c.word_count <= config.max_words for c in chunks)


def test_fenced_code_with_blank_lines_and_hash_never_split() -> None:
    code = "```bash\n\n# not a heading\n\necho hi\n\n```"
    filler = " ".join([f"w{i}" for i in range(200)])
    body = f"Intro paragraph.\n\n{code}\n\n{filler}"
    config = ChunkConfig(
        target_words=50,
        max_words=80,
        min_words=10,
        overlap_words=10,
        blog_base_url="https://example.com/blog/",
    )
    chunks = _chunk(body, config=config)
    joined = "\n".join(c.body for c in chunks)
    # Fence appears intact exactly once
    assert joined.count("```bash") == 1
    assert "# not a heading" in joined
    # The code block contents stay together in one chunk
    code_chunks = [c for c in chunks if "# not a heading" in c.body]
    assert len(code_chunks) == 1
    assert "```bash" in code_chunks[0].body and code_chunks[0].body.strip().endswith(
        "```"
    )


def test_small_section_merges_into_neighbor() -> None:
    body = (
        "## Big\n\n" + ("word " * 100) + "\n\n## Tiny\n\n" + "only a few words here.\n"
    )
    config = ChunkConfig(
        target_words=200,
        max_words=250,
        min_words=60,
        overlap_words=20,
        blog_base_url="https://example.com/blog/",
    )
    chunks = _chunk(body, config=config)
    # Tiny should not stand alone as its own section chunk
    assert not any(c.section == "Tiny" for c in chunks)
    assert any("## Tiny" in c.body or "only a few words" in c.body for c in chunks)


def test_stable_ids_and_content_hash() -> None:
    body = "## S\n\n" + ("alpha " * 50) + "\n\n" + ("beta " * 50)
    a = _chunk(body, slug="stable-post")
    b = _chunk(body, slug="stable-post")
    assert [c.id for c in a] == [c.id for c in b]
    assert [c.content_hash for c in a] == [c.content_hash for c in b]
    assert [c.id for c in a] == [f"stable-post#{i}" for i in range(len(a))]


def test_metadata_and_url_on_every_chunk() -> None:
    body = "Hello world with enough words to count as content here today."
    chunks = _chunk(
        body,
        title="Hello",
        slug="hello-world",
        published_at="2011-07-05T00:57:01.000Z",
    )
    assert len(chunks) == 1
    c = chunks[0]
    assert c.title == "Hello"
    assert c.slug == "hello-world"
    assert c.published_at == "2011-07-05T00:57:01.000Z"
    assert c.url == "https://example.com/blog/hello-world"
    assert c.source_type == "blog"
    assert c.embed_text.startswith("Hello")
    assert body.strip() in c.embed_text
    assert "updated_at" not in c.__dict__ or not hasattr(c, "updated_at")


def test_front_matter_parsing() -> None:
    text = (FIXTURES / "financing_dummies.md").read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    assert meta["title"].startswith("Financing Real Estate")
    assert meta["slug"].startswith("financing-real-estate")
    assert "published_at" in meta
    assert "updated_at" not in meta  # must not be used/stored
    assert body.lstrip().startswith("###")


def test_empty_body_produces_no_chunks() -> None:
    assert _chunk("") == []
    assert _chunk("   \n\n  ") == []


def test_non_ascii_text() -> None:
    body = "Café résumé — naïve façade. " * 5
    chunks = _chunk(body, title="Café", slug="cafe")
    assert len(chunks) == 1
    assert "Café" in chunks[0].body
    assert "façade" in chunks[0].body


def test_financing_fixture_keeps_headings_in_body() -> None:
    text = (FIXTURES / "financing_dummies.md").read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    chunks = _chunk(
        body,
        title=meta["title"],
        slug=meta["slug"],
        published_at=meta["published_at"],
    )
    assert len(chunks) == 1  # under target
    assert "### Synopsis" in chunks[0].body
    assert "### Review" in chunks[0].body


def test_domain_proxy_fixture_preserves_fenced_code() -> None:
    text = (FIXTURES / "domain_proxy_spaces.md").read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    chunks = _chunk(
        body,
        title=meta["title"],
        slug=meta["slug"],
        published_at=meta["published_at"],
    )
    joined = "\n".join(c.body for c in chunks)
    assert "```" in joined
    assert "proxy_cache_path" in joined
