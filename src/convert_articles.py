"""Convert raw article JSON cache into per-slug markdown files."""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from src.lexical import is_known_node_type, lexical_to_markdown

RAW_PATH = Path("data/raw/articles.json")
OUTPUT_DIR = Path("content/blog")
SHORT_ARTICLES_REPORT = Path("data/reports/short_articles.txt")
SHORT_BODY_WORD_LIMIT = 20

# Residual HTML tags in converted markdown (legitimate in posts that discuss HTML).
HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*\b[^>]*>")


def load_articles(path: Path = RAW_PATH) -> list[dict[str, Any]]:
    """Load the raw articles cache."""
    if not path.is_file():
        raise FileNotFoundError(f"Raw cache not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError(f"Expected a JSON list in {path}")
    return data


def article_root(article: dict[str, Any]) -> dict[str, Any]:
    """Return the Lexical root node for an article."""
    content = article.get("content")
    if not isinstance(content, dict):
        return {"type": "root", "children": []}
    root = content.get("root", content)
    if not isinstance(root, dict):
        return {"type": "root", "children": []}
    return root


def yaml_escape(value: str) -> str:
    """Quote a YAML scalar when it contains reserved characters."""
    if value == "":
        return '""'
    needs_quote = (
        bool(re.search(r'[:#\[\]{},&*!|>\'"%@`]|^[-?]', value))
        or value.strip() != value
    )
    if needs_quote or "\n" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def build_front_matter(article: dict[str, Any]) -> str:
    """Build YAML front matter for title/slug/published_at/updated_at."""
    title = str(article.get("title") or "")
    slug = str(article.get("slug") or "")
    published = article.get("publishedAt") or ""
    updated = article.get("updatedAt") or ""
    lines = [
        "---",
        f"title: {yaml_escape(title)}",
        f"slug: {yaml_escape(slug)}",
        f"published_at: {yaml_escape(str(published))}",
        f"updated_at: {yaml_escape(str(updated))}",
        "---",
        "",
    ]
    return "\n".join(lines)


def word_count(text: str) -> int:
    """Count whitespace-separated words in text."""
    return len(re.findall(r"\S+", text))


def _body_after_front_matter(contents: str) -> str:
    """Return markdown body after YAML front matter."""
    if contents.startswith("---"):
        end = contents.find("\n---", 3)
        if end != -1:
            return contents[end + 4 :].strip()
    return contents.strip()


def convert_article(
    article: dict[str, Any],
    *,
    stats: Counter[str] | None = None,
) -> tuple[str, str]:
    """Return (slug, full markdown file contents) for one article."""
    slug = str(article.get("slug") or "").strip()
    if not slug:
        raise ValueError(f"Article {article.get('id')!r} is missing a slug")

    body = lexical_to_markdown(article_root(article), stats=stats)
    return slug, build_front_matter(article) + (f"{body}\n" if body else "")


def reset_output_dir(path: Path = OUTPUT_DIR) -> None:
    """Remove and recreate the blog output directory (no stale files)."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_markdown(slug: str, contents: str, output_dir: Path = OUTPUT_DIR) -> Path:
    """Write one article markdown file."""
    path = output_dir / f"{slug}.md"
    path.write_text(contents, encoding="utf-8")
    return path


def body_contains_html_tags(body: str) -> bool:
    """Return True if markdown body still contains HTML tags."""
    return HTML_TAG_RE.search(body) is not None


def write_short_articles_report(
    slugs: list[str],
    path: Path = SHORT_ARTICLES_REPORT,
) -> None:
    """Write one slug per line for short/empty converted bodies."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{slug}\n" for slug in slugs), encoding="utf-8")


def print_report(
    *,
    converted: int,
    node_counts: Counter[str],
    short_or_empty: int,
    html_tag_files: int,
) -> None:
    """Print the conversion summary report."""
    print(f"Articles converted: {converted}")
    print("Node types seen:")
    for node_type, count in sorted(
        node_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        flag = "" if is_known_node_type(node_type) else "  (unknown)"
        print(f"  {node_type}: {count}{flag}")
    print(
        "Articles with empty or under-"
        f"{SHORT_BODY_WORD_LIMIT}-word bodies: {short_or_empty}"
    )
    print(f"Output files still containing HTML tags: {html_tag_files}")


def convert_all(
    raw_path: Path = RAW_PATH,
    output_dir: Path = OUTPUT_DIR,
    short_report_path: Path = SHORT_ARTICLES_REPORT,
) -> dict[str, Any]:
    """Convert every article in the raw cache into markdown files."""
    articles = load_articles(raw_path)
    reset_output_dir(output_dir)

    node_counts: Counter[str] = Counter()
    short_slugs: list[str] = []
    html_tag_files = 0

    for article in articles:
        slug, contents = convert_article(article, stats=node_counts)
        write_markdown(slug, contents, output_dir)
        body = _body_after_front_matter(contents)
        if word_count(body) < SHORT_BODY_WORD_LIMIT:
            short_slugs.append(slug)
        if body_contains_html_tags(body):
            html_tag_files += 1

    write_short_articles_report(short_slugs, short_report_path)
    print_report(
        converted=len(articles),
        node_counts=node_counts,
        short_or_empty=len(short_slugs),
        html_tag_files=html_tag_files,
    )
    return {
        "converted": len(articles),
        "node_counts": node_counts,
        "short_or_empty": len(short_slugs),
        "html_tag_files": html_tag_files,
        "short_slugs": short_slugs,
    }


def main() -> int:
    """CLI entry: convert data/raw/articles.json → content/blog/*.md."""
    try:
        convert_all()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
