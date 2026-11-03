"""Pure markdown chunking for embeddable blog passages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ChunkConfig:
    """Tunable chunk size / overlap settings (v1 defaults)."""

    target_words: int = 300
    max_words: int = 450
    min_words: int = 60
    overlap_words: int = 40
    blog_base_url: str = ""


@dataclass(frozen=True)
class Chunk:
    """One embeddable passage with retrieval metadata."""

    id: str
    content_hash: str
    title: str
    slug: str
    published_at: str
    section: str
    chunk_index: int
    url: str
    source_type: str
    body: str
    embed_text: str
    word_count: int
    oversize_code: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize public chunk fields for JSONL (report-only flags omitted)."""
        data = asdict(self)
        data.pop("oversize_code", None)
        return data


@dataclass
class _Section:
    heading: str
    parts: list[str]  # paragraphs or whole fenced code blocks


def word_count(text: str) -> int:
    """Count whitespace-separated words."""
    return len(re.findall(r"\S+", text))


def content_hash(body: str) -> str:
    """Stable hash of chunk body text for change detection."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def article_url(blog_base_url: str, slug: str) -> str:
    """Join blog base URL with slug."""
    base = blog_base_url.rstrip("/") + "/"
    return f"{base}{slug}"


def make_embed_text(title: str, section: str, body: str) -> str:
    """Build the text that will be embedded later (title/section prefix + body)."""
    if section:
        return f"{title}\nSection: {section}\n\n{body}"
    return f"{title}\n\n{body}"


def chunk_markdown(
    body: str,
    *,
    title: str,
    slug: str,
    published_at: str,
    config: ChunkConfig,
) -> list[Chunk]:
    """Split a markdown body into chunks. Pure: no file or network I/O."""
    body = body.strip()
    if not body:
        return []

    total_words = word_count(body)
    if total_words < config.target_words:
        return [
            _make_chunk(
                body=body,
                title=title,
                slug=slug,
                published_at=published_at,
                section="",
                index=0,
                config=config,
                oversize_code=False,
            )
        ]

    sections = _parse_sections(body)
    sections = _merge_small_sections(sections, config.min_words)

    raw_chunks: list[tuple[str, str, bool]] = []
    for section in sections:
        raw_chunks.extend(_chunk_section(section, config))

    chunks: list[Chunk] = []
    for index, (chunk_body, section_name, oversize_code) in enumerate(raw_chunks):
        chunks.append(
            _make_chunk(
                body=chunk_body,
                title=title,
                slug=slug,
                published_at=published_at,
                section=section_name,
                index=index,
                config=config,
                oversize_code=oversize_code,
            )
        )
    return chunks


def _make_chunk(
    *,
    body: str,
    title: str,
    slug: str,
    published_at: str,
    section: str,
    index: int,
    config: ChunkConfig,
    oversize_code: bool,
) -> Chunk:
    body = body.strip()
    return Chunk(
        id=f"{slug}#{index}",
        content_hash=content_hash(body),
        title=title,
        slug=slug,
        published_at=published_at,
        section=section,
        chunk_index=index,
        url=article_url(config.blog_base_url, slug),
        source_type="blog",
        body=body,
        embed_text=make_embed_text(title, section, body),
        word_count=word_count(body),
        oversize_code=oversize_code,
    )


def _is_fence_line(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("```", "~~~"))


def _fence_marker(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("```"):
        return "```"
    return "~~~"


def _is_heading_line(line: str) -> bool:
    return HEADING_RE.match(line.rstrip("\n")) is not None


def _parse_sections(body: str) -> list[_Section]:
    """Split markdown into heading sections; fences stay opaque units."""
    lines = body.splitlines()
    sections: list[_Section] = []
    heading = ""
    parts: list[str] = []
    para_lines: list[str] = []
    in_fence = False
    fence_mark = ""
    fence_lines: list[str] = []

    def flush_para() -> None:
        nonlocal para_lines
        if para_lines:
            text = "\n".join(para_lines).strip()
            if text:
                parts.append(text)
            para_lines = []

    def flush_section() -> None:
        nonlocal heading, parts
        flush_para()
        if heading or parts:
            sections.append(_Section(heading=heading, parts=list(parts)))
        heading = ""
        parts = []

    for line in lines:
        if in_fence:
            fence_lines.append(line)
            # Closing fence (same marker). Opening already consumed.
            if line.lstrip().startswith(fence_mark) and len(fence_lines) > 1:
                parts.append("\n".join(fence_lines).strip("\n"))
                fence_lines = []
                in_fence = False
                fence_mark = ""
            continue

        if _is_fence_line(line):
            flush_para()
            in_fence = True
            fence_mark = _fence_marker(line)
            fence_lines = [line]
            continue

        if _is_heading_line(line):
            flush_section()
            match = HEADING_RE.match(line.strip())
            assert match is not None
            heading = match.group(2).strip()
            # Keep the heading line as the first part of the section body.
            parts.append(line.strip())
            continue

        if not line.strip():
            flush_para()
            continue

        para_lines.append(line)

    if in_fence and fence_lines:
        # Unclosed fence: keep as one opaque part.
        parts.append("\n".join(fence_lines).strip("\n"))
    flush_section()
    return sections


def _section_text(section: _Section) -> str:
    return "\n\n".join(p for p in section.parts if p).strip()


def _merge_small_sections(sections: list[_Section], min_words: int) -> list[_Section]:
    """Merge sections under min_words into a neighbor within the article."""
    if not sections:
        return []

    merged: list[_Section] = []
    for section in sections:
        text = _section_text(section)
        if word_count(text) >= min_words or not merged:
            merged.append(_Section(heading=section.heading, parts=list(section.parts)))
            continue
        # Merge into previous neighbor; keep previous heading as section name.
        prev = merged[-1]
        prev.parts.extend(section.parts)

    # If the first section was tiny and we couldn't merge backward, merge forward.
    if len(merged) >= 2 and word_count(_section_text(merged[0])) < min_words:
        first = merged.pop(0)
        merged[0].parts = first.parts + merged[0].parts
        # Prefer the surviving (second) heading as the section label.
    return merged


def _is_code_part(part: str) -> bool:
    stripped = part.lstrip()
    return stripped.startswith(("```", "~~~"))


def _chunk_section(
    section: _Section, config: ChunkConfig
) -> list[tuple[str, str, bool]]:
    """Return (body, section_name, oversize_code) pieces for one section."""
    text = _section_text(section)
    if not text:
        return []

    if word_count(text) <= config.max_words:
        return [(text, section.heading, False)]

    parts = list(section.parts)
    chunks: list[tuple[str, str, bool]] = []
    cores: list[str] = []  # bodies without overlap prefix (for stable overlap)
    bucket: list[str] = []
    bucket_words = 0

    def content_budget() -> int:
        """Leave room for overlap on non-first chunks so totals stay <= max."""
        if not chunks:
            return config.max_words
        return max(config.max_words - config.overlap_words, 1)

    def emit_bucket() -> None:
        nonlocal bucket, bucket_words
        if not bucket:
            return
        core = "\n\n".join(bucket).strip()
        append_core(core, oversize_code=False)
        bucket = []
        bucket_words = 0

    def append_core(core: str, *, oversize_code: bool) -> None:
        core = core.strip()
        body = core
        if cores:
            overlap = _overlap_text(cores[-1], config.overlap_words)
            if overlap:
                body = f"{overlap}\n\n{core}"
        cores.append(core)
        chunks.append((body, section.heading, oversize_code))

    def append_with_overlap(body: str, *, oversize_code: bool) -> None:
        append_core(body, oversize_code=oversize_code)

    for part in parts:
        part_words = word_count(part)
        budget = content_budget()

        if _is_code_part(part):
            if part_words > config.max_words:
                emit_bucket()
                append_with_overlap(part, oversize_code=True)
                continue
            if bucket_words and bucket_words + part_words > budget:
                emit_bucket()
                budget = content_budget()
            if part_words > budget and not bucket:
                # Code fits under absolute max but not under overlap-adjusted budget:
                # emit alone without forcing a split inside the fence.
                append_with_overlap(part, oversize_code=False)
                continue
            bucket.append(part)
            bucket_words += part_words
            if bucket_words >= config.target_words:
                emit_bucket()
            continue

        if part_words > config.max_words:
            emit_bucket()
            for piece in _split_paragraph(part, config, limit=content_budget()):
                append_with_overlap(piece, oversize_code=False)
            continue

        if bucket_words and bucket_words + part_words > budget:
            emit_bucket()
            budget = content_budget()
        if part_words > budget and not bucket:
            for piece in _split_paragraph(part, config, limit=budget):
                append_with_overlap(piece, oversize_code=False)
            continue
        bucket.append(part)
        bucket_words += part_words
        if bucket_words >= min(config.target_words, budget):
            emit_bucket()

    emit_bucket()
    return chunks


def _split_paragraph(
    text: str, config: ChunkConfig, *, limit: int | None = None
) -> list[str]:
    """Split an oversize paragraph at sentence boundaries."""
    max_words = limit if limit is not None else config.max_words
    target = min(config.target_words, max_words)
    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        # Hard fallback: split by words so we never invent padding.
        words = text.split()
        pieces: list[str] = []
        size = max(target, 1)
        for i in range(0, len(words), size):
            pieces.append(" ".join(words[i : i + size]))
        return pieces or [text]

    pieces = []
    bucket: list[str] = []
    bucket_words = 0
    for sentence in sentences:
        sw = word_count(sentence)
        if bucket and bucket_words + sw > max_words:
            pieces.append(" ".join(bucket).strip())
            bucket = []
            bucket_words = 0
        if sw > max_words and not bucket:
            words = sentence.split()
            size = max(target, 1)
            for i in range(0, len(words), size):
                pieces.append(" ".join(words[i : i + size]))
            continue
        bucket.append(sentence)
        bucket_words += sw
        if bucket_words >= target:
            pieces.append(" ".join(bucket).strip())
            bucket = []
            bucket_words = 0
    if bucket:
        pieces.append(" ".join(bucket).strip())
    return pieces


def _split_sentences(text: str) -> list[str]:
    parts = SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _strip_fenced_blocks(text: str) -> str:
    """Remove fenced code so overlap never reprints opaque fences."""
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False
    fence_mark = ""
    for line in lines:
        if in_fence:
            if line.lstrip().startswith(fence_mark):
                in_fence = False
                fence_mark = ""
            continue
        if _is_fence_line(line):
            in_fence = True
            fence_mark = _fence_marker(line)
            continue
        out.append(line)
    return "\n".join(out).strip()


def _overlap_text(previous_body: str, overlap_words: int) -> str:
    """Last ~overlap_words words, preferring whole trailing sentences."""
    if overlap_words <= 0 or not previous_body.strip():
        return ""
    # Never overlap fenced code (opaque; also avoids duplicating fences).
    previous_body = _strip_fenced_blocks(previous_body)
    if not previous_body:
        return ""
    sentences = _split_sentences(previous_body)
    if not sentences:
        words = previous_body.split()
        return " ".join(words[-overlap_words:])

    chosen: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        sw = word_count(sentence)
        if chosen and total + sw > overlap_words and len(chosen) >= 1:
            break
        chosen.insert(0, sentence)
        total += sw
        # Prefer 1–2 sentences once we have enough overlap words.
        if total >= overlap_words and len(chosen) >= 1:
            break
    if len(chosen) > 2:
        chosen = chosen[-2:]
    return " ".join(chosen).strip()
