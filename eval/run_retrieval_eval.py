"""Run retrieval eval cases and optionally compare prefix settings."""

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
from src.retrieve import retrieve
from src.vector_store import NumpyVectorStore

CASES_PATH = Path("eval/retrieval_cases.json")
RESULTS_DIR = Path("data/eval")


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(
    cases: list[dict[str, Any]],
    *,
    k: int = 5,
    store: NumpyVectorStore | None = None,
    config: EmbedConfig | None = None,
) -> dict[str, Any]:
    """Evaluate hit rate@k and collect top-1 scores for every question."""
    vector_store = store or NumpyVectorStore.load(INDEX_DIR)
    cfg = config or load_embed_config()
    rows: list[dict[str, Any]] = []
    hits = 0
    on_topic = 0

    for case in cases:
        results = retrieve(
            case["question"],
            k=k,
            store=vector_store,
            config=cfg,
        )
        result_slugs = [r.slug for r in results]
        top1 = results[0].score if results else None
        expected = list(case.get("expected_slugs") or [])
        ranks: dict[str, int | None] = {}
        case_hit = False
        if case.get("off_topic"):
            # Off-topic: no expected slug; still record top-1 score for thresholding.
            case_hit = True  # does not count toward on-topic hit rate
        else:
            on_topic += 1
            for slug in expected:
                try:
                    ranks[slug] = result_slugs.index(slug) + 1
                except ValueError:
                    ranks[slug] = None
            case_hit = any(ranks[s] is not None for s in expected)
            if case_hit:
                hits += 1

        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "off_topic": bool(case.get("off_topic")),
                "needs_review": bool(case.get("needs_review")),
                "expected_slugs": expected,
                "ranks": ranks,
                "hit": case_hit if not case.get("off_topic") else None,
                "top1_score": top1,
                "top_ids": [r.id for r in results],
                "top_slugs": result_slugs,
            }
        )

    hit_rate = (hits / on_topic) if on_topic else 0.0
    return {
        "k": k,
        "on_topic_cases": on_topic,
        "hits": hits,
        "hit_rate_at_k": hit_rate,
        "cases": rows,
        "query_prefix": cfg.query_prefix,
        "doc_prefix": cfg.doc_prefix,
        "embed_model": cfg.model,
    }


def print_summary(result: dict[str, Any]) -> None:
    print(
        f"Hit rate@{result['k']}: {result['hit_rate_at_k']:.3f} "
        f"({result['hits']}/{result['on_topic_cases']})"
    )
    print(f"Prefixes: query={result['query_prefix']!r} doc={result['doc_prefix']!r}")
    for row in result["cases"]:
        top1 = row["top1_score"]
        top1_s = f"{top1:.4f}" if top1 is not None else "n/a"
        if row["off_topic"]:
            print(f"- {row['id']}: off-topic top1={top1_s}")
        else:
            print(f"- {row['id']}: hit={row['hit']} ranks={row['ranks']} top1={top1_s}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run retrieval evaluation cases")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument(
        "--compare-prefixes",
        action="store_true",
        help="Rebuild/index with and without nomic-style prefixes and compare hit rate",
    )
    args = parser.parse_args(argv)

    try:
        cases = load_cases()
        if not args.compare_prefixes:
            result = evaluate(cases, k=args.k)
            print_summary(result)
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out = RESULTS_DIR / f"retrieval_{stamp}.json"
            settings = load_settings()
            result["model"] = settings.llm_model
            result["prompt_hash"] = prompt_hash(
                load_system_prompt(
                    voice_samples=settings.voice_samples == "on",
                )
            )
            result["git_commit"] = git_commit()
            result["settings"] = settings.masked_dict()
            out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"Wrote {out}")
            return 0

        base = load_embed_config()
        variants = [
            ("no_prefix", "", ""),
            (
                "nomic_prefixes",
                "search_query: ",
                "search_document: ",
            ),
        ]
        summaries = []
        for name, q_prefix, d_prefix in variants:
            cfg = EmbedConfig(
                model=base.model,
                base_url=base.base_url,
                api_key=base.api_key,
                batch_size=base.batch_size,
                max_chars=base.max_chars,
                query_prefix=q_prefix,
                doc_prefix=d_prefix,
            )
            print(f"\n=== Building index: {name} ===")
            report = build_or_update_index(config=cfg, rebuild=True)
            print(
                f"embedded={report['embedded']} truncated={len(report['truncated_ids'])}"
            )
            store = NumpyVectorStore.load(INDEX_DIR)
            result = evaluate(cases, k=args.k, store=store, config=cfg)
            result["variant"] = name
            print_summary(result)
            summaries.append(result)

        winner = max(summaries, key=lambda r: (r["hit_rate_at_k"], r["variant"]))
        payload = {
            "compared_at": datetime.now(timezone.utc).isoformat(),
            "winner": winner["variant"],
            "variants": summaries,
            "model": load_settings().llm_model,
            "git_commit": git_commit(),
            "settings": load_settings().masked_dict(),
        }
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = RESULTS_DIR / f"prefix_compare_{stamp}.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"\nWinner: {winner['variant']} (hit_rate={winner['hit_rate_at_k']:.3f})")
        print(f"Wrote {out}")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
