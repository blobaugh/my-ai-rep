"""Cross RETRIEVAL_K with RETRIEVAL_QUERY_TURNS. Does not change defaults."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from eval.properties import load_rule_ngrams
from eval.run_regression_eval import (
    CONVERSATION_PATH,
    REGRESSION_PATH,
    build_run_settings,
    load_cases,
    run_conversations,
    run_regression,
)
from src.config import git_commit, prompt_hash
from src.prompt import load_system_prompt

OUT = Path("data/eval/benbot10_k_experiment.json")
FOCUS = [
    "Who is Ben?",
    "Who are you?",
    "What are you like to work for?",
    "What is your leadership style?",
    "What are you like as a boss?",
]


def main() -> int:
    ngrams = load_rule_ngrams()
    regression_cases = load_cases(REGRESSION_PATH)
    conversation_cases = load_cases(CONVERSATION_PATH)
    conditions = []
    for k in (4, 6, 8):
        for turns in (1, 2):
            settings = build_run_settings(retrieval_k=k, query_turns=turns)
            print(f"=== k={k} query_turns={turns} ===", flush=True)
            rows = run_regression(regression_cases, settings, ngrams=ngrams)
            scripts = run_conversations(conversation_cases, settings, ngrams=ngrams)
            passed = sum(1 for row in rows if row["flags_ok"])
            conv_passed = sum(1 for row in scripts if row["flags_ok"])
            print(
                f"regression {passed}/{len(rows)}  conversations {conv_passed}/{len(scripts)}",
                flush=True,
            )
            for row in rows:
                if row["question"] in FOCUS:
                    mark = "PASS" if row["flags_ok"] else "FAIL"
                    print(f"  [{mark}] {row['question']}: {row['reply']}", flush=True)
            system = load_system_prompt(
                stale_years=settings.source_stale_years,
                voice_samples=settings.voice_samples == "on",
                include_blog="blog" in settings.retrieval_sources,
            )
            conditions.append(
                {
                    "retrieval_k": k,
                    "retrieval_query_turns": turns,
                    "regression_passed": passed,
                    "regression_total": len(rows),
                    "conversation_passed": conv_passed,
                    "conversation_total": len(scripts),
                    "settings": settings.masked_dict(),
                    "model": settings.llm_model,
                    "prompt_hash": prompt_hash(system),
                    "git_commit": git_commit(),
                    "cases": rows,
                    "conversations": scripts,
                }
            )
            OUT.write_text(
                json.dumps(
                    {
                        "created_at": datetime.now(timezone.utc).strftime(
                            "%Y%m%dT%H%M%SZ"
                        ),
                        "conditions": conditions,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    print("EXPERIMENT DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
