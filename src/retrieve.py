"""Retrieve top chunks for a question from the vector index."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.config import load_embed_config, load_settings
from src.embeddings import EmbedConfig, embed_texts
from src.vector_store import NumpyVectorStore, SearchHit, VectorStore

INDEX_DIR = Path("data/index")


@dataclass(frozen=True)
class RetrievedChunk:
    """One retrieval hit with public chunk fields + similarity score."""

    id: str
    title: str
    slug: str
    url: str
    published_at: str
    section: str
    body: str
    source_type: str
    score: float
    content_hash: str
    match_kind: str = ""
    match_phrasing: str = ""


def hit_to_retrieved(hit: SearchHit) -> RetrievedChunk:
    """Map a store hit into the retrieve() result type."""
    meta = hit.metadata
    return RetrievedChunk(
        id=hit.id,
        title=str(meta.get("title", "")),
        slug=str(meta.get("slug", "")),
        url=str(meta.get("url", "")),
        published_at=str(meta.get("published_at", "")),
        section=str(meta.get("section", "")),
        body=str(meta.get("body", "")),
        source_type=str(meta.get("source_type", "")),
        score=hit.score,
        content_hash=hit.content_hash,
        match_kind=str(meta.get("match_kind", "") or ""),
        match_phrasing=str(meta.get("match_phrasing", "") or ""),
    )


def _prefers(candidate: SearchHit, current: SearchHit) -> bool:
    """Higher score wins. An equal score keeps the ``qa`` vector."""
    if candidate.score > current.score:
        return True
    if candidate.score < current.score:
        return False
    candidate_qa = str(candidate.metadata.get("kind") or "") == "qa"
    current_qa = str(current.metadata.get("kind") or "") == "qa"
    return candidate_qa and not current_qa


def collapse_to_entries(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """One hit per entry. Score is the max vector score. Ties keep kind ``qa``.

    The returned id is the entry id. ``match_kind`` and ``match_phrasing``
    record which vector won.
    """
    best: dict[str, SearchHit] = {}
    for hit in hits:
        entry_id = str(hit.metadata.get("entry_id") or hit.id)
        chosen = SearchHit(
            id=entry_id,
            score=hit.score,
            content_hash=str(hit.metadata.get("entry_content_hash") or hit.content_hash),
            metadata={
                **hit.metadata,
                "match_kind": str(hit.metadata.get("kind") or ""),
                "match_phrasing": str(hit.metadata.get("phrasing") or ""),
                "vector_id": hit.id,
            },
        )
        current = best.get(entry_id)
        if current is None or _prefers(chosen, current):
            best[entry_id] = chosen
    return sorted(best.values(), key=lambda item: item.score, reverse=True)


def dedupe_exact_by_hash(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """Keep the best-scoring copy of each content_hash."""
    best: dict[str, SearchHit] = {}
    order: list[str] = []
    for hit in hits:
        key = hit.content_hash
        if key not in best:
            best[key] = hit
            order.append(key)
        elif hit.score > best[key].score:
            best[key] = hit
    # Preserve score order
    return sorted((best[k] for k in order), key=lambda h: h.score, reverse=True)


def apply_per_article_cap(
    hits: Sequence[SearchHit], max_per_article: int
) -> list[SearchHit]:
    """Limit how many chunks from the same slug may appear."""
    if max_per_article <= 0:
        return []
    counts: dict[str, int] = {}
    kept: list[SearchHit] = []
    for hit in hits:
        slug = str(hit.metadata.get("slug") or "")
        n = counts.get(slug, 0)
        if n >= max_per_article:
            continue
        counts[slug] = n + 1
        kept.append(hit)
    return kept


def parse_retrieval_sources(raw: str | None) -> set[str] | None:
    """Parse RETRIEVAL_SOURCES. None = unset (caller default); empty set = no retrieval.

    ``none`` (any case) means no retrieval. Comma-separated types otherwise.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text or text.lower() == "none":
        return set()
    return {part.strip() for part in text.split(",") if part.strip()}


def retrieve(
    question: str,
    *,
    k: int | None = None,
    max_per_article: int = 2,
    min_score: float | None = None,
    source_type: str | None = None,
    source_types: set[str] | None = None,
    store: VectorStore | None = None,
    config: EmbedConfig | None = None,
    embed_fn: Callable[..., tuple[list[list[float]], list[bool]]] | None = None,
    index_dir: Path = INDEX_DIR,
    candidate_multiplier: int = 24,
) -> list[RetrievedChunk]:
    """Embed a question and return the top capped, de-duplicated chunks."""
    if not question.strip():
        return []
    # Explicit empty set means "retrieve nothing" (facts-only / sources=none).
    if source_types is not None and len(source_types) == 0:
        return []
    if k is None:
        k = load_settings().retrieval_k
    cfg = config or load_embed_config()
    vector_store = store or NumpyVectorStore.load(index_dir)
    embed = embed_fn or embed_texts

    vectors, _ = embed([question], config=cfg, kind="query")
    if not vectors:
        return []
    filters: dict[str, Any] = {}
    if source_types is not None:
        filters["source_types"] = source_types
    elif source_type is not None:
        filters["source_type"] = source_type

    # Over-fetch so caps / dedupe still fill k.
    fetch_k = max(k * candidate_multiplier, k)
    hits = vector_store.search(vectors[0], fetch_k, filters=filters or None)
    hits = collapse_to_entries(hits)
    hits = dedupe_exact_by_hash(hits)
    hits = apply_per_article_cap(hits, max_per_article)
    if min_score is not None:
        hits = [h for h in hits if h.score >= min_score]
    return [hit_to_retrieved(h) for h in hits[:k]]


def retrieve_timed(
    question: str,
    **kwargs: Any,
) -> tuple[list[RetrievedChunk], float, float]:
    """Like retrieve(), also returning (embed_seconds, search_seconds)."""
    cfg = kwargs.pop("config", None) or load_embed_config()
    store = kwargs.pop("store", None) or NumpyVectorStore.load(
        kwargs.get("index_dir", INDEX_DIR)
    )
    embed = kwargs.pop("embed_fn", None) or embed_texts
    kwargs.pop("index_dir", None)

    source_types = kwargs.get("source_types")
    if source_types is not None and len(source_types) == 0:
        return [], 0.0, 0.0

    t0 = time.perf_counter()
    vectors, _ = embed([question], config=cfg, kind="query")
    embed_s = time.perf_counter() - t0
    if not vectors:
        return [], embed_s, 0.0

    filters: dict[str, Any] = {}
    source_type = kwargs.get("source_type")
    if source_types is not None:
        filters["source_types"] = source_types
    elif source_type is not None:
        filters["source_type"] = source_type
    k = kwargs.get("k")
    if k is None:
        k = load_settings().retrieval_k
    fetch_k = max(k * kwargs.get("candidate_multiplier", 24), k)

    t1 = time.perf_counter()
    hits = store.search(vectors[0], fetch_k, filters=filters or None)
    search_s = time.perf_counter() - t1

    hits = collapse_to_entries(hits)
    hits = dedupe_exact_by_hash(hits)
    hits = apply_per_article_cap(hits, kwargs.get("max_per_article", 2))
    min_score = kwargs.get("min_score")
    if min_score is not None:
        hits = [h for h in hits if h.score >= min_score]
    results = [hit_to_retrieved(h) for h in hits[:k]]
    return results, embed_s, search_s


def format_retrieve_header(settings: Any) -> str:
    """One header line of the retrieval settings actually used."""
    if settings.retrieval_min_score is None:
        min_score = "unset"
    else:
        min_score = format(settings.retrieval_min_score, "g")
    sources = ",".join(sorted(settings.retrieval_sources)) or "none"
    return (
        "Effective settings: "
        f"RETRIEVAL_SOURCES={sources} "
        f"RETRIEVAL_K={settings.retrieval_k} "
        f"RETRIEVAL_MAX_PER_ARTICLE={settings.retrieval_max_per_article} "
        f"RETRIEVAL_MIN_SCORE={min_score} "
        f"EMBED_MODEL={settings.embed_model}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retrieve chunks using the same settings as the chat"
    )
    parser.add_argument("question", help="Natural-language question")
    parser.add_argument(
        "-k",
        type=int,
        default=None,
        help="Number of results (default: RETRIEVAL_K)",
    )
    parser.add_argument(
        "--max-per-article",
        type=int,
        default=None,
        help="Max chunks from the same article slug (default: RETRIEVAL_MAX_PER_ARTICLE)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Override RETRIEVAL_MIN_SCORE",
    )
    parser.add_argument(
        "--source-type",
        default=None,
        help="Optional single source_type filter when --sources is omitted",
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="Comma-separated source types (overrides RETRIEVAL_SOURCES; use none for empty)",
    )
    args = parser.parse_args(argv)

    try:
        from src.config import load_settings

        settings = load_settings()
        if args.k is not None:
            settings = settings.with_overrides(retrieval_k=args.k)
        if args.max_per_article is not None:
            settings = settings.with_overrides(
                retrieval_max_per_article=args.max_per_article
            )
        if args.min_score is not None:
            settings = settings.with_overrides(retrieval_min_score=args.min_score)
        if args.sources is not None:
            parsed = parse_retrieval_sources(args.sources) or set()
            unknown = sorted(part for part in parsed if part not in {"qa", "blog"})
            if unknown:
                raise ValueError(
                    "RETRIEVAL_SOURCES has unknown source type "
                    f"{unknown[0]!r}; expected qa or blog"
                )
            settings = settings.with_overrides(retrieval_sources=frozenset(parsed))
            source_types: set[str] | None = set(settings.retrieval_sources)
            source_type = None
        elif args.source_type is not None:
            source_types = None
            source_type = args.source_type
        else:
            source_types = set(settings.retrieval_sources)
            source_type = None
        print(format_retrieve_header(settings))
        results, embed_s, search_s = retrieve_timed(
            args.question,
            k=settings.retrieval_k,
            max_per_article=settings.retrieval_max_per_article,
            min_score=settings.retrieval_min_score,
            source_type=source_type,
            source_types=source_types,
            config=settings.to_embed_config(),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Query embed time: {embed_s:.3f}s")
    print(f"Search time: {search_s:.3f}s")
    print(f"Results: {len(results)}")
    for rank, item in enumerate(results, start=1):
        print(f"{rank}. {item.score:.4f}  {item.id}  [{item.slug}]  {item.title}")
        snippet = item.body.replace("\n", " ")
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        print(f"   {snippet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
