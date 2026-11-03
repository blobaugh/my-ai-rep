"""Compare prompt variants on the regression, conversation, and guardrail sets.

Does not change defaults. Each case is a fresh answer_turn, except multi-turn
scripts, which keep history only inside the script.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from eval.properties import rule_ngrams
from eval.run_guardrail_eval import load_cases as load_guardrail
from eval.run_guardrail_eval import run_case
from eval.run_regression_eval import (
    CONVERSATION_PATH,
    REGRESSION_PATH,
    build_run_settings,
    load_cases,
    run_conversations,
    run_regression,
)
from src.prompt import load_system_prompt

OUT = Path("data/eval/benbot12_variants.json")
VARIANTS = ("v1", "v2", "v3")
BROAD = {
    "background",
    "tell-background",
    "what-do-you-do",
    "who-is-ben",
    "who-are-you",
    "work-for",
    "leadership-style",
    "like-as-boss",
}


def _ok(row: dict) -> bool:
    if "flags_ok" in row:
        return bool(row["flags_ok"])
    return row.get("flag_pass_rate") == 1


def _passed(rows: list[dict]) -> int:
    return sum(1 for row in rows if _ok(row))


def main() -> int:
    missing = [name for name in VARIANTS if not Path(f"prompts/variants/{name}.md").is_file()]
    if missing:
        print(
            "prompts/variants was removed in BENBOT-34; this comparison cannot run.",
            file=sys.stderr,
        )
        return 1
    settings = build_run_settings()
    regression_cases = load_cases(REGRESSION_PATH)
    scripts = load_cases(CONVERSATION_PATH)
    guard_cases = load_guardrail()
    payload: dict = {"variants": []}
    if OUT.is_file():
        payload = json.loads(OUT.read_text(encoding="utf-8"))
    done = {item["variant"] for item in payload.get("variants", [])}
    for name in VARIANTS:
        if name in done:
            print(f"skip {name}", flush=True)
            continue
        path = Path(f"prompts/variants/{name}.md")
        system = load_system_prompt(
            stale_years=settings.source_stale_years,
            prompt_path=path,
            voice_samples=settings.voice_samples == "on",
            include_blog="blog" in settings.retrieval_sources,
        )
        ngrams = rule_ngrams(path.read_text(encoding="utf-8"))
        print(f"=== {name} regression ===", flush=True)
        regression = run_regression(
            regression_cases, settings, ngrams=ngrams, system_prompt=system
        )
        for row in regression:
            mark = "PASS" if row["flags_ok"] else "FAIL"
            print(f"[{mark}] {row['id']}: {row['reply'][:160]}", flush=True)
        print(f"=== {name} conversations ===", flush=True)
        conversations = run_conversations(
            scripts, settings, ngrams=ngrams, system_prompt=system
        )
        for script in conversations:
            mark = "PASS" if script["flags_ok"] else "FAIL"
            print(f"[{mark}] {script['id']}", flush=True)
        print(f"=== {name} guardrail ===", flush=True)
        guardrail = []
        for case in guard_cases:
            row = run_case(
                case, settings=settings, client=None, ngrams=ngrams, system_prompt=system
            )
            mark = "PASS" if _ok(row) else "FAIL"
            print(f"[{mark}] {row['id']}: {row['reply'][:140]}", flush=True)
            guardrail.append(row)
        broad_rows = [row for row in regression if row["id"] in BROAD]
        other_rows = [row for row in regression if row["id"] not in BROAD]
        item = {
            "variant": name,
            "broad_passed": _passed(broad_rows),
            "broad_total": len(broad_rows),
            "other_passed": _passed(other_rows),
            "other_total": len(other_rows),
            "conversation_passed": _passed(conversations),
            "conversation_total": len(conversations),
            "guardrail_passed": _passed(guardrail),
            "guardrail_total": len(guardrail),
            "regression": regression,
            "conversations": conversations,
            "guardrail": guardrail,
        }
        payload.setdefault("variants", []).append(item)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            f"{name}: broad {item['broad_passed']}/{item['broad_total']} "
            f"other {item['other_passed']}/{item['other_total']} "
            f"conv {item['conversation_passed']}/{item['conversation_total']} "
            f"guard {item['guardrail_passed']}/{item['guardrail_total']}",
            flush=True,
        )
    print(f"Wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
