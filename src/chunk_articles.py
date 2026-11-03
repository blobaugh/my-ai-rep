"""Chunk blog markdown files into data/chunks/chunks.jsonl."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.chunking import Chunk, ChunkConfig, chunk_markdown

BLOG_DIR = Path("content/blog")
OUTPUT_PATH = Path("data/chunks/chunks.jsonl")
DIVIDER = "\n" + ("=" * 72) + "\n"


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML front matter; drop updated_at (migration date, not editorial)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in fm_block.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key == "updated_at":
            continue
        meta[key] = _strip_yaml_scalar(value.strip())
    return meta, body


def _strip_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_blog_base_url() -> str:
    """Return BLOG_BASE_URL from settings."""
    from src.config import load_settings

    url = load_settings().blog_base_url.strip()
    if not url:
        raise RuntimeError("BLOG_BASE_URL is not set in the environment or .env")
    return url


def default_config(blog_base_url: str | None = None) -> ChunkConfig:
    """Build the v1 ChunkConfig, optionally overriding the blog base URL."""
    return ChunkConfig(blog_base_url=blog_base_url or load_blog_base_url())


def iter_article_paths(blog_dir: Path = BLOG_DIR) -> list[Path]:
    """Return markdown paths sorted by slug for deterministic output."""
    return sorted(blog_dir.glob("*.md"), key=lambda p: p.stem)


def chunk_article_file(
    path: Path, config: ChunkConfig
) -> tuple[list[Chunk], str | None]:
    """Chunk one article file. Returns (chunks, skip_reason)."""
    text = path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    slug = meta.get("slug") or path.stem
    title = meta.get("title") or slug
    published_at = meta.get("published_at") or ""
    if not body.strip():
        return [], "empty body"
    chunks = chunk_markdown(
        body,
        title=title,
        slug=slug,
        published_at=published_at,
        config=config,
    )
    if not chunks:
        return [], "empty body"
    return chunks, None


def write_jsonl(chunks: list[Chunk], path: Path = OUTPUT_PATH) -> None:
    """Write chunks as deterministic JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            c.to_json_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        for c in chunks
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def print_report(
    *,
    processed: int,
    skipped: list[tuple[str, str]],
    chunks: list[Chunk],
    chunks_per_article: list[int],
) -> None:
    """Print the chunking summary report."""
    words = [c.word_count for c in chunks]
    oversize_code = sum(1 for c in chunks if c.oversize_code)
    single_chunk_articles = sum(1 for n in chunks_per_article if n == 1)
    largest = sorted(chunks, key=lambda c: c.word_count, reverse=True)[:5]

    print(f"Articles processed: {processed}")
    print(f"Articles skipped: {len(skipped)}")
    for slug, reason in skipped:
        print(f"  - {slug}: {reason}")
    print(f"Total chunks: {len(chunks)}")
    if chunks_per_article:
        print(
            "Chunks per article: "
            f"min={min(chunks_per_article)} "
            f"median={_median(chunks_per_article):.1f} "
            f"max={max(chunks_per_article)}"
        )
    else:
        print("Chunks per article: min=0 median=0.0 max=0")
    if words:
        print(
            "Chunk words: "
            f"min={min(words)} "
            f"median={_median(words):.1f} "
            f"p95={_percentile(words, 95):.1f} "
            f"max={max(words)}"
        )
    else:
        print("Chunk words: min=0 median=0.0 p95=0.0 max=0")
    print(f"Oversize code chunks: {oversize_code}")
    print(f"Single-chunk articles: {single_chunk_articles}")
    print("5 largest chunks:")
    for chunk in largest:
        flag = " (oversize code)" if chunk.oversize_code else ""
        print(f"  - {chunk.id}: {chunk.word_count} words{flag}")


def show_article_chunks(
    slug: str, config: ChunkConfig, blog_dir: Path = BLOG_DIR
) -> int:
    """Print chunks for one slug with clear dividers."""
    path = blog_dir / f"{slug}.md"
    if not path.is_file():
        print(f"error: no article at {path}", file=sys.stderr)
        return 1
    chunks, skip_reason = chunk_article_file(path, config)
    if skip_reason:
        print(f"Skipped {slug}: {skip_reason}")
        return 0
    print(f"Chunks for {slug}: {len(chunks)}")
    for chunk in chunks:
        print(DIVIDER)
        print(
            f"id={chunk.id}  section={chunk.section!r}  "
            f"words={chunk.word_count}  oversize_code={chunk.oversize_code}"
        )
        print(DIVIDER)
        print(chunk.body)
    print(DIVIDER)
    return 0


def run_chunk_all(
    *,
    blog_dir: Path = BLOG_DIR,
    output_path: Path = OUTPUT_PATH,
    config: ChunkConfig | None = None,
) -> dict[str, Any]:
    """Chunk every blog markdown file and write JSONL + report."""
    cfg = config or default_config()
    all_chunks: list[Chunk] = []
    skipped: list[tuple[str, str]] = []
    chunks_per_article: list[int] = []
    processed = 0

    for path in iter_article_paths(blog_dir):
        processed += 1
        chunks, skip_reason = chunk_article_file(path, cfg)
        if skip_reason:
            skipped.append((path.stem, skip_reason))
            chunks_per_article.append(0)
            continue
        chunks_per_article.append(len(chunks))
        all_chunks.extend(chunks)

    # Deterministic order: already walking sorted slugs; re-sort by id as safety.
    all_chunks.sort(key=lambda c: (c.slug, c.chunk_index))
    write_jsonl(all_chunks, output_path)
    print_report(
        processed=processed,
        skipped=skipped,
        chunks=all_chunks,
        chunks_per_article=[n for n in chunks_per_article if n > 0],
    )

    # Validate max words (except oversize code).
    violations = [
        c for c in all_chunks if c.word_count > cfg.max_words and not c.oversize_code
    ]
    if violations:
        print(
            f"warning: {len(violations)} chunks exceed max_words without oversize_code flag",
            file=sys.stderr,
        )

    return {
        "processed": processed,
        "skipped": skipped,
        "chunks": all_chunks,
        "output": str(output_path),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry for chunking blog articles."""
    parser = argparse.ArgumentParser(description="Chunk blog markdown into JSONL")
    parser.add_argument(
        "--show",
        metavar="SLUG",
        help="Print chunks for one article instead of writing JSONL",
    )
    args = parser.parse_args(argv)

    try:
        config = default_config()
        if args.show:
            return show_article_chunks(args.show, config)
        run_chunk_all(config=config)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
