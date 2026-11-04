"""Compare chat models on the fixed eval suites (BENBOT-31).

Points LLM_PRIMARY_* at each candidate (OpenRouter) or the local baseline.
Embeddings stay on the configured embedder. Temperature 0.
"""

from __future__ import annotations

import argparse
import json
import statistics
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.properties import load_rule_ngrams
from eval.run_gap_eval import CASES_PATH as GAP_PATH
from eval.run_gap_eval import run_gap
from eval.run_guardrail_eval import CASES_PATH as GUARD_PATH
from eval.run_guardrail_eval import load_cases as load_guard
from eval.run_guardrail_eval import run_case as run_guard_case
from eval.run_regression_eval import (
    CONVERSATION_PATH,
    REGRESSION_PATH,
    RESULTS_DIR,
    build_run_settings,
    load_cases,
    repair_summary,
    run_conversations,
    run_regression,
)
from src.config import Settings, load_settings
from src.pipeline import answer_turn
from src.prompt import load_system_prompt

ACCEPTANCE_PATH = Path("eval/acceptance_cases.json")
MODELS_API = "https://openrouter.ai/api/v1/models"
KEY_API = "https://openrouter.ai/api/v1/auth/key"
SOURCE_NOTE = "OpenRouter GET /api/v1/models (2026-11-03)"

DEFAULT_CANDIDATES = (
    "meta-llama/llama-3.1-8b-instruct",
    "meta-llama/llama-3.2-3b-instruct",
    "openai/gpt-4o-mini",
    "qwen/qwen-2.5-7b-instruct",
)


def fetch_openrouter_models(api_key: str) -> list[dict[str, Any]]:
    req = urllib.request.Request(
        MODELS_API,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.load(resp)
    return list(payload.get("data") or [])


def fetch_key_usage(api_key: str) -> dict[str, Any]:
    req = urllib.request.Request(
        KEY_API,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.URLError:
        return {}


def model_record(models: list[dict[str, Any]], model_id: str) -> dict[str, Any] | None:
    for row in models:
        if row.get("id") == model_id:
            return row
    return None


def settings_for_model(base: Settings, label: str, model_id: str | None) -> Settings:
    settings = build_run_settings(temperature=0.0, base=base)
    if label == "baseline-local":
        return settings.with_overrides(
            llm_secondary_base_url="",
            llm_secondary_api_key="",
            llm_secondary_model="",
        )
    if not base.llm_secondary_base_url or not base.llm_secondary_api_key:
        raise ValueError("OpenRouter requires LLM_SECONDARY_* in .env")
    if not model_id:
        raise ValueError(f"model id required for {label}")
    return settings.with_overrides(
        llm_base_url=base.llm_secondary_base_url,
        llm_api_key=base.llm_secondary_api_key,
        llm_model=model_id,
        llm_secondary_base_url="",
        llm_secondary_api_key="",
        llm_secondary_model="",
    )


def run_acceptance(
    cases: list[dict[str, Any]], settings: Settings
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        answer = answer_turn(case["question"], [], settings)
        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "reply": answer.text,
                "category": answer.debug.get("category"),
                "outcome_flags": list(answer.debug.get("outcome_flags") or []),
                "repair": answer.debug.get("repair") or "none",
                "removed_sentences": list(answer.debug.get("removed_sentences") or []),
                "verification": answer.debug.get("verification"),
                "timings": answer.debug.get("timings") or {},
                "usage": answer.debug.get("usage"),
                "model_calls": int(answer.debug.get("model_calls") or 0),
            }
        )
    return rows


def collect_turn_metrics(all_turns: list[dict[str, Any]]) -> dict[str, Any]:
    times = [
        float((turn.get("timings") or {}).get("total"))
        for turn in all_turns
        if isinstance((turn.get("timings") or {}).get("total"), (int, float))
    ]
    prompt_tokens = 0
    completion_tokens = 0
    for turn in all_turns:
        usage = turn.get("usage")
        if isinstance(usage, dict):
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
    prunes = sum(1 for turn in all_turns if turn.get("repair") == "prune")
    retries = sum(1 for turn in all_turns if turn.get("repair") == "retry")
    fallbacks = sum(1 for turn in all_turns if turn.get("repair") == "fallback")
    calls = [int(turn.get("model_calls") or 0) for turn in all_turns]
    p95 = None
    if times:
        ordered = sorted(times)
        p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    return {
        "turns": len(all_turns),
        "prunes": prunes,
        "retries": retries,
        "fallbacks": fallbacks,
        "mean_model_calls": statistics.mean(calls) if calls else 0.0,
        "mean_s": statistics.mean(times) if times else 0.0,
        "p95_s": p95,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


def flatten_turns(
    regression: list[dict[str, Any]],
    conversations: list[dict[str, Any]],
    guardrail: list[dict[str, Any]],
    gap: list[dict[str, Any]],
    acceptance: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for row in regression:
        copy = dict(row)
        copy["_suite"] = "regression"
        turns.append(copy)
    for script in conversations:
        for turn in script.get("turns") or []:
            copy = dict(turn)
            copy["_suite"] = "conversation"
            turns.append(copy)
    for row in guardrail:
        for run in row.get("runs") or []:
            copy = dict(run)
            copy["_suite"] = "guardrail"
            turns.append(copy)
    for row in gap:
        copy = dict(row)
        copy["_suite"] = "gap"
        turns.append(copy)
    for row in acceptance:
        copy = dict(row)
        copy["_suite"] = "acceptance"
        turns.append(copy)
    return turns


def estimate_cost_usd(
    metrics: dict[str, Any], pricing: dict[str, str] | None
) -> float | None:
    if not pricing:
        return None
    try:
        pin = float(pricing.get("prompt") or 0)
        pout = float(pricing.get("completion") or 0)
    except ValueError:
        return None
    prompt = metrics["prompt_tokens"]
    completion = metrics["completion_tokens"]
    return prompt * pin + completion * pout


def run_one_label(
    label: str,
    model_id: str | None,
    base: Settings,
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    settings = settings_for_model(base, label, model_id)
    system = load_system_prompt(
        voice_samples=settings.voice_samples == "on",
        bot_name=settings.bot_name,
        human_name=settings.human_name,
    )
    ngrams = load_rule_ngrams(
        human_name=settings.human_name, bot_name=settings.bot_name
    )
    regression = run_regression(
        load_cases(REGRESSION_PATH), settings, ngrams=ngrams, system_prompt=system
    )
    conversations = run_conversations(
        load_cases(CONVERSATION_PATH), settings, ngrams=ngrams, system_prompt=system
    )
    guard_rows = [
        run_guard_case(case, settings=settings, client=None, ngrams=ngrams, repeats=1)
        for case in load_guard(GUARD_PATH)
    ]
    gap = run_gap(load_cases(GAP_PATH), settings)
    acceptance = run_acceptance(load_cases(ACCEPTANCE_PATH), settings)
    all_turns = flatten_turns(regression, conversations, guard_rows, gap, acceptance)
    metrics = collect_turn_metrics(all_turns)
    meta = model_record(catalog, model_id) if model_id else None
    pricing = (meta or {}).get("pricing")
    cost_per_100 = None
    per_run = estimate_cost_usd(metrics, pricing)
    if per_run is not None and metrics["turns"]:
        cost_per_100 = per_run * (100.0 / metrics["turns"])
    hard_regression = sum(1 for row in regression if not row["flags_ok"])
    hard_conv = sum(1 for row in conversations if not row["flags_ok"])
    guard_fail = sum(1 for row in guard_rows if row.get("flag_pass_rate", 1) < 1.0)
    gap_rows = [row for row in gap if row.get("group") == "gap"]
    gap_no_answer = sum(1 for row in gap_rows if row.get("category") == "no_answer")
    pruned = [
        {
            "suite": turn.get("_suite"),
            "id": turn.get("id"),
            "removed": turn.get("removed_sentences") or [],
            "question": turn.get("question"),
        }
        for turn in all_turns
        if turn.get("removed_sentences")
    ]
    return {
        "label": label,
        "model_id": model_id or settings.llm_model,
        "settings_model": settings.llm_model,
        "openrouter_meta": meta,
        "metrics": metrics,
        "suites": {
            "regression_fail": hard_regression,
            "conversation_fail": hard_conv,
            "guardrail_fail": guard_fail,
            "gap_no_answer_rate": (
                gap_no_answer / len(gap_rows) if gap_rows else None
            ),
            "repair_summary": {
                "regression": repair_summary("regression", regression),
                "conversations": repair_summary(
                    "conversations",
                    [t for s in conversations for t in s.get("turns") or []],
                ),
            },
        },
        "false_prune_candidates": pruned,
        "cost_usd_this_run": per_run,
        "cost_usd_per_100_turns": cost_per_100,
        "raw": {
            "regression": regression,
            "conversations": conversations,
            "guardrail": guard_rows,
            "gap": gap,
            "acceptance": acceptance,
        },
    }


def print_summary_table(rows: list[dict[str, Any]]) -> None:
    header = (
        "label",
        "model",
        "reg_fail",
        "conv_fail",
        "guard_fail",
        "gap_no_answer%",
        "prune",
        "retry",
        "fallback",
        "mean_s",
        "p95_s",
        "tok_in",
        "tok_out",
        "$/100turn",
    )
    print("\t".join(header))
    for row in rows:
        m = row["metrics"]
        suites = row["suites"]
        gap_rate = suites.get("gap_no_answer_rate")
        gap_pct = f"{100 * gap_rate:.0f}" if gap_rate is not None else "-"
        cost = row.get("cost_usd_per_100_turns")
        cost_s = f"{cost:.4f}" if cost is not None else "-"
        print(
            "\t".join(
                [
                    row["label"],
                    row["model_id"],
                    str(suites["regression_fail"]),
                    str(suites["conversation_fail"]),
                    str(suites["guardrail_fail"]),
                    gap_pct,
                    str(m["prunes"]),
                    str(m["retries"]),
                    str(m["fallbacks"]),
                    f"{m['mean_s']:.2f}",
                    f"{m['p95_s']:.2f}" if m["p95_s"] is not None else "-",
                    str(m["prompt_tokens"]),
                    str(m["completion_tokens"]),
                    cost_s,
                ]
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare models on BenBot eval suites")
    parser.add_argument(
        "--models",
        nargs="*",
        default=list(DEFAULT_CANDIDATES),
        help="OpenRouter model ids (baseline-local is always included)",
    )
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        help="Skip local benbot-llama baseline",
    )
    parser.add_argument("--tag", default="benbot31")
    args = parser.parse_args(argv)

    base = load_settings()
    usage_before = fetch_key_usage(base.llm_secondary_api_key)
    catalog = fetch_openrouter_models(base.llm_secondary_api_key)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_DIR / f"compare_models_{args.tag}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "openrouter_catalog.json").write_text(
        json.dumps({"source": SOURCE_NOTE, "models": catalog}, indent=2),
        encoding="utf-8",
    )

    labels: list[tuple[str, str | None]] = []
    if not args.skip_baseline:
        labels.append(("baseline-local", None))
    for model_id in args.models:
        labels.append((model_id.replace("/", "_"), model_id))

    results: list[dict[str, Any]] = []
    for label, model_id in labels:
        print(f"=== {label} ({model_id or 'local'}) ===", flush=True)
        payload = run_one_label(label, model_id, base, catalog)
        path = out_dir / f"{label}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        results.append(payload)
        print(f"Wrote {path}", flush=True)

    usage_after = fetch_key_usage(base.llm_secondary_api_key)
    summary = {
        "created_at": stamp,
        "source": SOURCE_NOTE,
        "candidates": args.models,
        "usage_before": usage_before,
        "usage_after": usage_after,
        "results": [
            {
                "label": row["label"],
                "model_id": row["model_id"],
                "metrics": row["metrics"],
                "suites": row["suites"],
                "cost_usd_this_run": row.get("cost_usd_this_run"),
                "cost_usd_per_100_turns": row.get("cost_usd_per_100_turns"),
            }
            for row in results
        ],
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print_summary_table(results)
    print(f"\nSummary: {summary_path}")
    if usage_before and usage_after:
        used = usage_after.get("usage") or usage_after.get("data", {}).get("usage")
        print(f"OpenRouter key usage snapshot: {used}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
