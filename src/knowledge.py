"""Turn every markdown file under the content directory into chunk records.

``about.md`` is prompt context and is not indexed. A file that uses the Q&A
entry format is indexed as questions and answers. Any other markdown file is
split on headings and indexed as prose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.qa import content_hash, entry_to_chunk, parse_qa

KNOWLEDGE_CHUNKS_PATH = Path("data/chunks/knowledge.jsonl")
_ABOUT_NAMES = frozenset({"about.md", "about.example.md"})
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_QA_HEADING_RE = re.compile(r"^##\s+\S+\s*$", re.MULTILINE)
_QA_Q_RE = re.compile(r"^Q:\s*\S", re.MULTILINE)
_QA_A_RE = re.compile(r"^A:\s*\S", re.MULTILINE)
_QA_SOURCE_RE = re.compile(r"^source:\s*\S", re.MULTILINE)
_QA_REVIEW_RE = re.compile(r"^review:\s*(draft|approved)\s*$", re.MULTILINE)


def looks_like_qa(text: str) -> bool:
    """True when the file uses the optional Q&A entry format.

    A heading plus a question, an answer, and the bookkeeping fields. A
    prose note that merely contains one of those lines stays prose.
    """
    return all(
        pattern.search(text) is not None
        for pattern in (
            _QA_HEADING_RE,
            _QA_Q_RE,
            _QA_A_RE,
            _QA_SOURCE_RE,
            _QA_REVIEW_RE,
        )
    )


def content_markdown_files(root: Path) -> list[Path]:
    """Markdown files under ``root``, except the always-on about file."""
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        if path.name in _ABOUT_NAMES and path.parent.resolve() == root.resolve():
            continue
        files.append(path)
    return files


def _file_slug(path: Path, root: Path) -> str:
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    return rel.removesuffix(".md").replace("/", "-")


def chunk_prose(path: Path, root: Path, text: str) -> list[dict]:
    """One chunk per heading section. A file with no headings is one chunk."""
    sections: list[tuple[str, str]] = []
    heading = ""
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append((heading, body))

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            buf = []
            heading = match.group(1).strip()
        else:
            buf.append(line)
    flush()
    if not sections and text.strip():
        sections = [(path.stem, text.strip())]

    slug = _file_slug(path, root)
    chunks: list[dict] = []
    for index, (title, body) in enumerate(sections):
        label = title or path.stem
        chunks.append(
            {
                "id": f"prose#{slug}#{index}",
                "content_hash": content_hash(f"{label}\n{body}"),
                "title": label,
                "slug": f"{slug}-{index}",
                "published_at": "",
                "section": "",
                "url": "",
                "source_type": "prose",
                "body": body,
                "embed_text": f"{label}\n\n{body}",
                "word_count": len(re.findall(r"\S+", body)),
            }
        )
    return chunks


def chunks_for_file(path: Path, root: Path, *, embed_mode: str) -> list[dict]:
    """Parse one markdown file as Q&A or as prose."""
    text = path.read_text(encoding="utf-8")
    if looks_like_qa(text):
        slug = _file_slug(path, root)
        chunks: list[dict] = []
        for entry in parse_qa(text):
            chunk = entry_to_chunk(entry, embed_mode=embed_mode)  # type: ignore[arg-type]
            chunk["id"] = f"qa#{slug}#{entry.id}"
            chunks.append(chunk)
        return chunks
    return chunk_prose(path, root, text)


def build_content_chunks(root: Path, *, embed_mode: str) -> list[dict]:
    """Chunks for every searchable markdown file under ``root``."""
    chunks: list[dict] = []
    seen: set[str] = set()
    for path in content_markdown_files(root):
        for chunk in chunks_for_file(path, root, embed_mode=embed_mode):
            cid = str(chunk["id"])
            if cid in seen:
                raise ValueError(f"duplicate chunk id {cid!r} from {path}")
            seen.add(cid)
            chunks.append(chunk)
    return chunks


def write_content_chunks(
    root: Path,
    path: Path = KNOWLEDGE_CHUNKS_PATH,
    *,
    embed_mode: str,
) -> int:
    """Write one JSONL of every searchable content file. Returns the row count."""
    chunks = build_content_chunks(root, embed_mode=embed_mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(chunk, ensure_ascii=False) for chunk in chunks]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)
