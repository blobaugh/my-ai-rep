"""Manual ingest: validate content, embed into a staging index, swap atomically."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from src.config import load_settings
from src.embeddings import EmbedConfig
from src.index_chunks import (
    IndexCompatibilityError,
    build_or_update_index,
    print_report,
)
from src.knowledge import (
    KNOWLEDGE_CHUNKS_PATH,
    ContentValidationError,
    build_content_chunks,
    validate_content,
)

INDEX_DIR = Path("data/index")
CHUNKS_DIR = Path("data/chunks")


def content_root(settings=None) -> Path:
    settings = settings or load_settings()
    root = Path(settings.content_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[1] / root
    return root


def write_chunks_jsonl(chunks: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(chunk, ensure_ascii=False) for chunk in chunks]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def publish_file(staging: Path, live: Path) -> None:
    live.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, live)


def publish_index(staging_dir: Path, live_dir: Path) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)
    for name in ("index.json", "vectors.npy"):
        src = staging_dir / name
        if not src.is_file():
            raise FileNotFoundError(f"missing {name} in staging index")
        publish_file(src, live_dir / name)


def run_ingest(
    *,
    check_only: bool = False,
    rebuild: bool = False,
    content_dir: Path | None = None,
    index_dir: Path = INDEX_DIR,
    chunks_path: Path = KNOWLEDGE_CHUNKS_PATH,
    embed_fn: Callable[..., tuple[list[list[float]], list[bool]]] | None = None,
    config: EmbedConfig | None = None,
) -> dict[str, Any]:
    """Validate content, optionally embed, and swap a new index into place."""
    settings = load_settings()
    root = content_dir or content_root(settings)
    validate_content(root)
    mode = settings.qa_embed_mode
    chunks = build_content_chunks(root, embed_mode=mode)
    if check_only:
        return {
            "embedded": 0,
            "unchanged": 0,
            "removed": 0,
            "truncated_ids": [],
            "elapsed_seconds": 0.0,
            "total_indexed": len(chunks),
            "qa_embed_mode": mode,
            "qa_vector_mode": "",
            "q_vector_prefix": "",
            "check_only": True,
            "files": len(list(root.rglob("*.md"))),
        }

    work = Path(tempfile.mkdtemp(prefix="benbot-ingest-"))
    try:
        staging_index = work / "index"
        staging_chunks = work / "knowledge.jsonl"
        write_chunks_jsonl(chunks, staging_chunks)
        report = build_or_update_index(
            chunks_path=staging_chunks,
            index_dir=staging_index,
            existing_index_dir=None if rebuild else index_dir,
            rebuild=rebuild,
            embed_fn=embed_fn,
            config=config,
        )
        publish_index(staging_index, index_dir)
        publish_file(staging_chunks, chunks_path)
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate content and rebuild the vector index safely"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Parse and validate content only; do not embed",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Discard the existing index and re-embed everything",
    )
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        report = run_ingest(check_only=args.check, rebuild=args.rebuild)
    except ContentValidationError as exc:
        location = exc.path.as_posix()
        if exc.line is not None:
            print(f"error: {location}: line {exc.line}: {exc.message}", file=sys.stderr)
        else:
            print(f"error: {location}: {exc.message}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except IndexCompatibilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if report.get("check_only"):
        elapsed = time.perf_counter() - started
        print(f"Check ok: {report['total_indexed']} chunks from content")
        print(f"Elapsed: {elapsed:.2f}s")
        return 0
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
