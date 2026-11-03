"""Build / incrementally update the NumPy vector index from chunk JSONL files."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

from src.config import load_embed_config, load_settings
from src.embeddings import EmbedConfig, embed_texts
from src.qa import (
    Q_VECTOR_PREFIX_KIND,
    QA_EMBED_MODES,
    QaEmbedMode,
    expand_multi_vectors,
    make_qa_embed_text,
)
from src.vector_store import (
    IndexMeta,
    NumpyVectorStore,
    VectorRecord,
    VectorStore,
    new_index_meta,
)

CHUNKS_PATH = Path("data/chunks/chunks.jsonl")
CHUNKS_DIR = Path("data/chunks")
INDEX_DIR = Path("data/index")


class IndexCompatibilityError(RuntimeError):
    """Raised when an existing index cannot be updated in place."""


def load_chunks(path: Path = CHUNKS_PATH) -> list[dict[str, Any]]:
    """Load chunk JSON objects from a single JSONL file."""
    if not path.is_file():
        raise FileNotFoundError(f"chunks file not found: {path}")
    chunks: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunks.append(json.loads(line))
    return chunks


def load_all_chunks(directory: Path = CHUNKS_DIR) -> list[dict[str, Any]]:
    """Load chunk JSONL files. ``chunks.jsonl`` is leftover blog output and is skipped."""
    if not directory.is_dir():
        raise FileNotFoundError(f"chunks directory not found: {directory}")
    paths = [
        path
        for path in sorted(directory.glob("*.jsonl"))
        if path.name != "chunks.jsonl"
    ]
    if not paths:
        raise FileNotFoundError(f"no *.jsonl files in {directory}")
    chunks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in paths:
        for chunk in load_chunks(path):
            cid = chunk.get("id")
            if not cid:
                raise ValueError(f"{path}: chunk missing id")
            if cid in seen_ids:
                raise ValueError(f"duplicate chunk id {cid!r} across JSONL files")
            seen_ids.add(cid)
            chunks.append(chunk)
    return chunks


def chunk_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    """Metadata fields persisted next to each vector (no updated_at)."""
    meta = {
        "title": chunk.get("title", ""),
        "slug": chunk.get("slug", ""),
        "url": chunk.get("url", ""),
        "published_at": chunk.get("published_at", ""),
        "section": chunk.get("section", ""),
        "body": chunk.get("body", ""),
        "source_type": chunk.get("source_type", ""),
        "embed_text": chunk.get("embed_text", ""),
    }
    for key in ("entry_id", "kind", "phrasing", "entry_content_hash"):
        if chunk.get(key) not in (None, ""):
            meta[key] = chunk[key]
    return meta


def check_compatible(existing: IndexMeta, config: EmbedConfig) -> None:
    """Refuse to mix models / prefixes / max_chars without --rebuild."""
    problems: list[str] = []
    if existing.embed_model != config.model:
        problems.append(f"embed model {existing.embed_model!r} != {config.model!r}")
    if existing.query_prefix != config.query_prefix:
        problems.append("query_prefix changed")
    if existing.doc_prefix != config.doc_prefix:
        problems.append("doc_prefix changed")
    if existing.max_chars and existing.max_chars != config.max_chars:
        problems.append(f"max_chars {existing.max_chars} != {config.max_chars}")
    if problems:
        raise IndexCompatibilityError(
            "Existing index is incompatible ("
            + "; ".join(problems)
            + "). Re-run with --rebuild to replace it."
        )


def plan_updates(
    chunks: Sequence[dict[str, Any]],
    existing_hashes: dict[str, str] | None,
    *,
    force_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Return (to_embed, unchanged_ids, remove_ids)."""
    force = force_ids or set()
    by_id = {c["id"]: c for c in chunks}
    if not existing_hashes:
        return list(chunks), [], []
    to_embed: list[dict[str, Any]] = []
    unchanged: list[str] = []
    for chunk_id, chunk in by_id.items():
        if chunk_id in force:
            to_embed.append(chunk)
        elif existing_hashes.get(chunk_id) == chunk.get("content_hash"):
            unchanged.append(chunk_id)
        else:
            to_embed.append(chunk)
    remove_ids = [cid for cid in existing_hashes if cid not in by_id]
    return to_embed, unchanged, remove_ids


def _make_store(
    *,
    config: EmbedConfig,
    dimension: int,
    factory: Callable[[IndexMeta], VectorStore],
    created_at: str | None = None,
    qa_embed_mode: str = "",
    qa_vector_mode: str = "",
    q_vector_prefix: str = "",
) -> VectorStore:
    meta = new_index_meta(
        embed_model=config.model,
        dimension=dimension,
        query_prefix=config.query_prefix,
        doc_prefix=config.doc_prefix,
        max_chars=config.max_chars,
        qa_embed_mode=qa_embed_mode,
        qa_vector_mode=qa_vector_mode,
        q_vector_prefix=q_vector_prefix,
    )
    if created_at:
        meta = IndexMeta(
            embed_model=meta.embed_model,
            dimension=meta.dimension,
            query_prefix=meta.query_prefix,
            doc_prefix=meta.doc_prefix,
            created_at=created_at,
            max_chars=meta.max_chars,
            qa_embed_mode=qa_embed_mode,
            qa_vector_mode=qa_vector_mode,
            q_vector_prefix=q_vector_prefix,
        )
    return factory(meta)


def vector_mode_for(embed_mode: str) -> str:
    """``multi`` uses several vectors per entry. The other modes use one."""
    return "multi" if embed_mode == "multi" else "single"


def stored_vector_mode(meta: IndexMeta) -> str:
    """Infer single-vector indexes written before qa_vector_mode existed."""
    if meta.qa_vector_mode:
        return meta.qa_vector_mode
    return "multi" if meta.qa_embed_mode == "multi" else "single"


def _entry_ids(chunks: Sequence[dict[str, Any]]) -> set[str]:
    """Ids of Q&A and facts rows (one per entry, before multi expansion)."""
    return {
        c["id"]
        for c in chunks
        if str(c.get("source_type", "")) in {"qa", "facts"}
        or str(c.get("id", "")).startswith("qa#")
        or str(c.get("id", "")).startswith("facts#")
    }


def apply_qa_embed_mode(
    chunks: Sequence[dict[str, Any]], mode: QaEmbedMode | str
) -> list[dict[str, Any]]:
    """Ensure Q&A rows use embed_text for the active QA_EMBED_MODE."""
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if str(chunk.get("source_type", "")) not in {"qa", "facts"}:
            out.append(chunk)
            continue
        updated = dict(chunk)
        updated["embed_text"] = make_qa_embed_text(
            str(updated.get("title", "")),
            str(updated.get("body", "")),
            mode=mode,  # type: ignore[arg-type]
        )
        out.append(updated)
    return out


def _embed_rows(
    rows: Sequence[dict[str, Any]],
    embed: Callable[..., tuple[list[list[float]], list[bool]]],
    cfg: EmbedConfig,
) -> tuple[list[list[float]], list[bool]]:
    """Embed rows, using each row's ``embed_kind`` (document or query)."""
    vectors: list[list[float] | None] = [None] * len(rows)
    flags = [False] * len(rows)
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        kind = str(row.get("embed_kind") or "document")
        groups.setdefault(kind, []).append(index)
    for kind, indexes in groups.items():
        texts = [rows[i].get("embed_text") or rows[i].get("body") or "" for i in indexes]
        embedded, truncated = embed(texts, config=cfg, kind=kind)
        if len(embedded) != len(indexes):
            raise RuntimeError("embed_fn returned a mismatched vector count")
        for offset, index in enumerate(indexes):
            vectors[index] = embedded[offset]
            flags[index] = truncated[offset]
    if any(vector is None for vector in vectors):
        raise RuntimeError("embed_fn left a row without a vector")
    return [vector for vector in vectors if vector is not None], flags


def build_or_update_index(
    *,
    chunks_path: Path | None = None,
    chunks_dir: Path = CHUNKS_DIR,
    index_dir: Path = INDEX_DIR,
    existing_index_dir: Path | None = None,
    config: EmbedConfig | None = None,
    rebuild: bool = False,
    embed_fn: Callable[..., tuple[list[list[float]], list[bool]]] | None = None,
    store_factory: Callable[[IndexMeta], VectorStore] | None = None,
    qa_embed_mode: QaEmbedMode | str | None = None,
    q_vector_prefix: str | None = None,
) -> dict[str, Any]:
    """Embed new/changed chunks and persist the vector index."""
    cfg = config or load_embed_config()
    if chunks_path is not None:
        chunks = load_chunks(chunks_path)
    else:
        chunks = load_all_chunks(chunks_dir)
    embed = embed_fn or embed_texts
    factory = store_factory or NumpyVectorStore
    mode = qa_embed_mode if qa_embed_mode is not None else load_settings().qa_embed_mode
    if mode not in QA_EMBED_MODES:
        raise ValueError(f"QA_EMBED_MODE must be one of {QA_EMBED_MODES}, got {mode!r}")
    q_prefix = q_vector_prefix or Q_VECTOR_PREFIX_KIND
    if q_prefix not in {"query", "document"}:
        raise ValueError(f"q_vector_prefix must be query or document, got {q_prefix!r}")
    desired_vector_mode = vector_mode_for(str(mode))
    text_mode = "question_and_answer" if mode == "multi" else mode
    chunks = apply_qa_embed_mode(chunks, text_mode)

    source_index_dir = (
        existing_index_dir if existing_index_dir is not None else index_dir
    )
    existing: VectorStore | None = None
    if not rebuild and (source_index_dir / "index.json").is_file():
        existing = NumpyVectorStore.load(source_index_dir)
        check_compatible(existing.meta, cfg)
        stored = stored_vector_mode(existing.meta)
        if stored != desired_vector_mode:
            raise IndexCompatibilityError(
                f"Index qa_vector_mode is {stored!r} but QA_EMBED_MODE={mode!r} "
                f"needs qa_vector_mode={desired_vector_mode!r}. "
                "Re-run with --rebuild to replace the index."
            )
        if desired_vector_mode == "multi":
            stored_prefix = existing.meta.q_vector_prefix or ""
            if stored_prefix and stored_prefix != q_prefix:
                raise IndexCompatibilityError(
                    f"Index q_vector_prefix is {stored_prefix!r} but this run uses "
                    f"{q_prefix!r}. Re-run with --rebuild to replace the index."
                )

    if mode == "multi":
        chunks = expand_multi_vectors(chunks, q_embed_kind=q_prefix)

    existing_hashes = None if rebuild or existing is None else existing.content_hashes()
    force_ids: set[str] = set()
    if (
        existing is not None
        and not rebuild
        and (existing.meta.qa_embed_mode or "") != mode
    ):
        force_ids = _entry_ids(chunks)

    to_embed, unchanged, remove_ids = plan_updates(
        chunks, existing_hashes, force_ids=force_ids
    )

    truncated_ids: list[str] = []
    started = time.perf_counter()

    if existing is not None and not rebuild:
        store: VectorStore = existing
        m = store.meta
        store._meta = IndexMeta(  # type: ignore[attr-defined]
            embed_model=m.embed_model,
            dimension=m.dimension,
            query_prefix=m.query_prefix,
            doc_prefix=m.doc_prefix,
            created_at=m.created_at,
            max_chars=m.max_chars,
            qa_embed_mode=str(mode),
            qa_vector_mode=desired_vector_mode,
            q_vector_prefix=q_prefix if mode == "multi" else "",
        )
    else:
        store = _make_store(
            config=cfg,
            dimension=1,
            factory=factory,
            qa_embed_mode=str(mode),
            qa_vector_mode=desired_vector_mode,
            q_vector_prefix=q_prefix if mode == "multi" else "",
        )

    if to_embed:
        vectors, trunc_flags = _embed_rows(to_embed, embed, cfg)
        if len(vectors) != len(to_embed):
            raise RuntimeError("embed_fn returned a mismatched vector count")
        dim = len(vectors[0])
        if store.meta.dimension not in {1, dim}:
            raise IndexCompatibilityError(
                f"embedded dimension {dim} != index dimension {store.meta.dimension}. "
                "Re-run with --rebuild."
            )
        if store.meta.dimension == 1 and dim != 1:
            created = None if rebuild or existing is None else existing.meta.created_at
            store = _make_store(
                config=cfg,
                dimension=dim,
                factory=factory,
                created_at=created,
                qa_embed_mode=str(mode),
                qa_vector_mode=desired_vector_mode,
                q_vector_prefix=q_prefix if mode == "multi" else "",
            )
            # If we had an existing store with real vectors, we already branched
            # above; this path is fresh/rebuild only.

        records = []
        for chunk, vector, was_trunc in zip(to_embed, vectors, trunc_flags):
            if was_trunc:
                truncated_ids.append(chunk["id"])
            records.append(
                VectorRecord(
                    id=chunk["id"],
                    vector=vector,
                    content_hash=chunk["content_hash"],
                    metadata=chunk_metadata(chunk),
                )
            )
        store.upsert(records)
    elif existing is None or rebuild:
        if not chunks:
            store = _make_store(
                config=cfg,
                dimension=1,
                factory=factory,
                qa_embed_mode=str(mode),
                qa_vector_mode=desired_vector_mode,
                q_vector_prefix=q_prefix if mode == "multi" else "",
            )

    if remove_ids and existing is not None and not rebuild:
        store.remove(remove_ids)

    store.save(index_dir)
    elapsed = time.perf_counter() - started
    return {
        "embedded": len(to_embed),
        "unchanged": len(unchanged),
        "removed": len(remove_ids),
        "truncated_ids": truncated_ids,
        "elapsed_seconds": elapsed,
        "total_indexed": len(store.ids()),
        "qa_embed_mode": mode,
        "qa_vector_mode": desired_vector_mode,
        "q_vector_prefix": q_prefix if mode == "multi" else "",
        "forced_qa_reembed": len(force_ids),
    }


def print_report(report: dict[str, Any]) -> None:
    """Print the indexing summary."""
    print(f"Embedded: {report['embedded']}")
    print(f"Unchanged: {report['unchanged']}")
    print(f"Removed: {report['removed']}")
    truncated = report["truncated_ids"]
    print(f"Truncated: {len(truncated)}")
    for chunk_id in truncated:
        print(f"  - {chunk_id}")
    print(f"Total indexed: {report['total_indexed']}")
    print(f"QA embed mode: {report.get('qa_embed_mode', '')}")
    print(f"QA vector mode: {report.get('qa_vector_mode', '')}")
    if report.get("q_vector_prefix"):
        print(f"Q vector prefix: {report.get('q_vector_prefix')}")
    print(f"Elapsed: {report['elapsed_seconds']:.2f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed chunks into the vector index")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Discard the existing index and re-embed everything",
    )
    args = parser.parse_args(argv)
    try:
        from src.knowledge import KNOWLEDGE_CHUNKS_PATH

        report = build_or_update_index(
            chunks_path=KNOWLEDGE_CHUNKS_PATH, rebuild=args.rebuild
        )
        print_report(report)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
