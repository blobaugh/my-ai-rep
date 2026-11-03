"""Evaluate Q&A retrieval hit rate / MRR under each QA_EMBED_MODE."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import git_commit, load_embed_config, load_settings, prompt_hash
from src.embeddings import EmbedConfig
from src.index_chunks import INDEX_DIR, build_or_update_index
from src.prompt import load_system_prompt
from src.qa import Q_VECTOR_PREFIX_KIND, QA_EMBED_MODES, write_knowledge_chunks
from src.retrieve import retrieve
from src.vector_store import NumpyVectorStore

CASES_PATH = Path("eval/qa_retrieval_cases.json")
RESULTS_DIR = Path("data/eval")
REPORT_QUESTIONS = (
    "What are you like to work for?",
    "What is your leadership style?",
    "Who is Ben?",
    "What's your background?",
    "Are you married?",
    "Tell me about Uganda",
    "Do you play any instruments?",
    "Do you keep fish?",
    "Tell me about your family",
)


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def mean_reciprocal_rank(ranks: list[int | None]) -> float:
    scores = [1.0 / r for r in ranks if r is not None and r > 0]
    if not scores:
        return 0.0
    return sum(scores) / len(ranks)


def evaluate(
    cases: list[dict[str, Any]],
    *,
    k: int = 4,
    store: NumpyVectorStore | None = None,
    config: EmbedConfig | None = None,
) -> dict[str, Any]:
    vector_store = store or NumpyVectorStore.load(INDEX_DIR)
    cfg = config or load_embed_config()
    rows: list[dict[str, Any]] = []
    hits = 0
    mrr_ranks: list[int | None] = []
    broad_total = 0
    broad_all = 0

    for case in cases:
        results = retrieve(
            case["question"],
            k=k,
            max_per_article=2,
            store=vector_store,
            config=cfg,
            source_types={"qa", "facts"},
        )
        result_slugs = [r.slug for r in results]
        expected = list(case.get("expected_slugs") or [])
        ranks: dict[str, int | None] = {}
        best: int | None = None
        for slug in expected:
            try:
                rank = result_slugs.index(slug) + 1
            except ValueError:
                rank = None
            ranks[slug] = rank
            if rank is not None and (best is None or rank < best):
                best = rank
        case_hit = best is not None
        if case_hit:
            hits += 1
        mrr_ranks.append(best)
        all_in = bool(expected) and all(
            ranks[slug] is not None and ranks[slug] <= k for slug in expected
        )
        if case.get("broad"):
            broad_total += 1
            if all_in:
                broad_all += 1
        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "expected_slugs": expected,
                "ranks": ranks,
                "hit": case_hit,
                "best_rank": best,
                "all_expected_in_top_k": all_in,
                "top1_score": results[0].score if results else None,
                "top_ids": [r.id for r in results],
                "top_slugs": result_slugs,
                "top": [
                    {
                        "id": item.id,
                        "slug": item.slug,
                        "score": item.score,
                        "kind": item.match_kind,
                        "phrasing": item.match_phrasing,
                    }
                    for item in results
                ],
                "needs_review": bool(case.get("needs_review")),
                "hard": bool(case.get("hard")),
                "broad": bool(case.get("broad")),
            }
        )

    n = len(cases) or 1
    return {
        "k": k,
        "cases_count": len(cases),
        "hits": hits,
        "hit_rate_at_k": hits / n,
        "mrr": mean_reciprocal_rank(mrr_ranks),
        "all_expected_in_top_k": (broad_all / broad_total) if broad_total else None,
        "all_expected_hits": broad_all,
        "all_expected_cases": broad_total,
        "report_questions": _report_questions(vector_store, cfg),
        "cases": rows,
        "qa_embed_mode": vector_store.meta.qa_embed_mode,
        "embed_model": cfg.model,
        "query_prefix": cfg.query_prefix,
        "doc_prefix": cfg.doc_prefix,
    }


def print_summary(result: dict[str, Any]) -> None:
    print(
        f"mode={result['qa_embed_mode']}  "
        f"hit@{result['k']}={result['hit_rate_at_k']:.3f} "
        f"({result['hits']}/{result['cases_count']})  "
        f"mrr={result['mrr']:.3f}  "
        f"all_expected={result.get('all_expected_hits')}/{result.get('all_expected_cases')}"
    )
    for row in result["cases"]:
        mark = "HIT" if row["hit"] else "MISS"
        print(
            f"  [{mark}] {row['id']}: best={row['best_rank']} "
            f"top1={row['top1_score']} tops={row['top_slugs'][:3]}"
        )


def _report_questions(store: NumpyVectorStore, cfg: EmbedConfig) -> list[dict[str, Any]]:
    rows = []
    for question in REPORT_QUESTIONS:
        results = retrieve(
            question,
            k=8,
            max_per_article=2,
            store=store,
            config=cfg,
            source_types={"qa", "facts"},
        )
        rows.append(
            {
                "question": question,
                "top": [
                    {
                        "id": item.id,
                        "slug": item.slug,
                        "score": round(item.score, 4),
                        "kind": item.match_kind,
                        "phrasing": item.match_phrasing,
                    }
                    for item in results
                ],
            }
        )
    return rows


def reindex_for_mode(
    mode: str, *, q_vector_prefix: str | None = None, rebuild: bool = False
) -> None:
    write_knowledge_chunks(mode)
    build_or_update_index(
        qa_embed_mode=mode,
        q_vector_prefix=q_vector_prefix or Q_VECTOR_PREFIX_KIND,
        rebuild=rebuild,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Q&A retrieval eval")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("-k", type=int, default=4)
    parser.add_argument(
        "--modes",
        default=",".join(QA_EMBED_MODES),
        help="Comma-separated QA_EMBED_MODE values to compare",
    )
    parser.add_argument(
        "--skip-reindex",
        action="store_true",
        help="Evaluate the current index only (ignore --modes rebuild)",
    )
    parser.add_argument(
        "--q-prefix",
        default="",
        help="For multi mode, query or document. Empty uses the code default.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Pass --rebuild to the index build (required when vector mode changes)",
    )
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    all_results: list[dict[str, Any]] = []

    try:
        if args.skip_reindex:
            result = evaluate(cases, k=args.k)
            print_summary(result)
            all_results.append(result)
        else:
            for mode in modes:
                prefix = args.q_prefix or None
                print(f"--- reindex QA_EMBED_MODE={mode} q_prefix={prefix or 'default'} ---")
                reindex_for_mode(
                    mode,
                    q_vector_prefix=prefix,
                    rebuild=args.rebuild or mode == "multi",
                )
                result = evaluate(cases, k=args.k)
                if prefix:
                    result["q_vector_prefix"] = prefix
                print_summary(result)
                all_results.append(result)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = RESULTS_DIR / f"qa_retrieval_{stamp}.json"
    settings = load_settings()
    payload = {
        "created_at": stamp,
        "model": settings.llm_model,
        "embed_model": settings.embed_model,
        "prompt_hash": prompt_hash(
            load_system_prompt(
                stale_years=settings.source_stale_years,
                voice_samples=settings.voice_samples == "on",
                include_blog="blog" in settings.retrieval_sources,
            )
        ),
        "git_commit": git_commit(),
        "settings": settings.masked_dict(),
        "results": all_results,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {out}")

    if len(all_results) >= 2:
        best = max(all_results, key=lambda r: (r["hit_rate_at_k"], r["mrr"]))
        print(
            f"Winner by hit@k then MRR: {best['qa_embed_mode']} "
            f"(hit={best['hit_rate_at_k']:.3f}, mrr={best['mrr']:.3f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
