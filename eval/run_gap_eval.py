"""Measure categories on gap, off-topic, and answerable questions.

Each question is a fresh session through answer_turn. Exit 0 always.
This is a measurement, not a pass/fail gate.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.run_regression_eval import RESULTS_DIR, envelope, load_cases
from src.config import load_settings
from src.pipeline import answer_turn

CASES_PATH = Path("eval/gap_cases.json")
GROUPS = ("gap", "off_topic", "answerable")


def run_gap(cases: list[dict[str, Any]], settings: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        answer = answer_turn(case["question"], [], settings)
        rows.append(
            {
                "id": case["id"],
                "group": case["group"],
                "question": case["question"],
                "needs_review": bool(case.get("needs_review")),
                "reply": answer.text,
                "category": answer.debug.get("category"),
                "outcome_flags": list(answer.debug.get("outcome_flags") or []),
                "top_score": answer.debug.get("top_score"),
                "repair": answer.debug.get("repair") or "none",
                "finish_reason": answer.finish_reason,
                "connection_used": answer.debug.get("connection_used"),
                "failover_active": bool(answer.debug.get("failover_active")),
            }
        )
    return rows


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        value = row.get(key)
        if isinstance(value, list):
            for item in value:
                counter[str(item)] += 1
            if not value:
                counter["(none)"] += 1
        else:
            counter[str(value)] += 1
    return dict(sorted(counter.items()))


def main() -> int:
    cases = load_cases(CASES_PATH)
    settings = load_settings()
    rows = run_gap(cases, settings)
    gap_rows = [row for row in rows if row["group"] == "gap"]
    no_answer = sum(1 for row in gap_rows if row["category"] == "no_answer")
    fallbacks = sum(1 for row in gap_rows if "repair_fallback" in row["outcome_flags"])
    print(
        f"gap no_answer {no_answer}/{len(gap_rows)}"
        f"  repair_fallback {fallbacks}/{len(gap_rows)}"
    )
    for group in GROUPS:
        group_rows = [row for row in rows if row["group"] == group]
        print(f"=== {group} ({len(group_rows)}) ===")
        print(f"categories {_counts(group_rows, 'category')}")
        print(f"flags {_counts(group_rows, 'outcome_flags')}")
    print("=== gap answers ===")
    for row in gap_rows:
        print(f"[{row['category']}] {row['id']}: {row['reply']}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = envelope(settings, "", rows)
    payload["summary"] = {
        group: {
            "count": len([row for row in rows if row["group"] == group]),
            "categories": _counts(
                [row for row in rows if row["group"] == group], "category"
            ),
            "flags": _counts(
                [row for row in rows if row["group"] == group], "outcome_flags"
            ),
        }
        for group in GROUPS
    }
    payload["gap_no_answer"] = {"count": no_answer, "total": len(gap_rows)}
    payload["gap_repair_fallback"] = {"count": fallbacks, "total": len(gap_rows)}
    out = RESULTS_DIR / f"gap_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
