"""Run regression and multi-turn cases through answer_turn. Each case is fresh."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.properties import load_rule_ngrams, run_check
from src.config import Settings, git_commit, load_settings, prompt_hash
from src.pipeline import answer_turn, append_turn
from src.prompt import load_system_prompt

REGRESSION_PATH = Path("eval/regression_cases.json")
CONVERSATION_PATH = Path("eval/conversation_cases.json")
RESULTS_DIR = Path("data/eval")


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_knowledge(answer: Any) -> str:
    """Knowledge the model was given. Not the rules (those name the banned words)."""
    return str(answer.debug.get("knowledge_text") or "")


def _checks(
    text: str,
    specs: list[dict[str, Any]],
    ngrams: set,
    knowledge: str = "",
    *,
    human_name: str = "",
    bot_name: str = "",
) -> list[dict[str, Any]]:
    full = list(specs)
    if not any(spec.get("name") == "no_unsupported_characterization" for spec in full):
        full.append({"name": "no_unsupported_characterization"})
    return [
        run_check(
            text,
            spec,
            ngrams=ngrams,
            knowledge=knowledge,
            human_name=human_name,
            bot_name=bot_name,
        ).as_dict()
        for spec in full
    ]


def run_regression(
    cases: list[dict[str, Any]],
    settings: Settings,
    *,
    ngrams: set,
    client: Any = None,
    system_prompt: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        answer = answer_turn(
            case["question"], [], settings, clients=client, system_prompt=system_prompt
        )
        flags = _checks(
            answer.text,
            list(case.get("checks") or []),
            ngrams,
            check_knowledge(answer),
            human_name=settings.human_name,
            bot_name=settings.bot_name,
        )
        rows.append(_row(case["id"], case["question"], answer, flags))
    return rows


def run_conversations(
    scripts: list[dict[str, Any]],
    settings: Settings,
    *,
    ngrams: set,
    client: Any = None,
    system_prompt: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for script in scripts:
        history: list[dict[str, str]] = []
        turns = []
        for turn in script["turns"]:
            answer = answer_turn(
                turn["question"],
                history,
                settings,
                clients=client,
                system_prompt=system_prompt,
            )
            flags = _checks(
                answer.text,
                list(turn.get("checks") or []),
                ngrams,
                check_knowledge(answer),
                human_name=settings.human_name,
                bot_name=settings.bot_name,
            )
            flags.extend(_retrieval_flags(answer, turn.get("expect_retrieval") or {}))
            turns.append(_row(script["id"], turn["question"], answer, flags))
            if answer.finish_reason != "invalid":
                history = append_turn(
                    history,
                    turn["question"].strip(),
                    answer.text,
                    settings.history_turns,
                )
        hard_fail = any(
            (not flag["ok"]) and not flag.get("advisory")
            for turn in turns
            for flag in turn["flags"]
        )
        rows.append(
            {
                "id": script["id"],
                "turns": turns,
                "flags_ok": not hard_fail,
            }
        )
    return rows


def _retrieval_flags(answer: Any, expect: dict[str, Any]) -> list[dict[str, Any]]:
    """Optional retrieval assertions for multi-turn scripts."""
    if not expect:
        return []
    retrieved = answer.debug.get("retrieved") or []
    slugs = [str(item.get("slug") or "") for item in retrieved]
    flags: list[dict[str, Any]] = []
    any_slugs = list(expect.get("any_slugs") or [])
    if any_slugs:
        ok = any(slug in slugs for slug in any_slugs)
        flags.append(
            {
                "name": "retrieval_any",
                "ok": ok,
                "advisory": False,
                "detail": f"wanted one of {any_slugs}, got {slugs}",
            }
        )
    first = expect.get("first_slug")
    if first:
        got = slugs[0] if slugs else ""
        flags.append(
            {
                "name": "retrieval_first",
                "ok": got == first,
                "advisory": False,
                "detail": f"wanted {first} first, got {got}",
            }
        )
    return flags


def _row(case_id: str, question: str, answer: Any, flags: list[dict[str, Any]]) -> dict[str, Any]:
    hard = [flag for flag in flags if not flag["ok"] and not flag.get("advisory")]
    return {
        "id": case_id,
        "question": question,
        "reply": answer.text,
        "sources": answer.sources_block,
        "flags": flags,
        "flagged": hard,
        "flags_ok": not hard,
        "retrieval": answer.debug.get("retrieved"),
        "finish_reason": answer.finish_reason,
        "query_used": answer.debug.get("query_used"),
        "knowledge_text": answer.debug.get("knowledge_text") or "",
        "verification": answer.debug.get("verification"),
        "retry_used": bool(answer.debug.get("retry_used")),
        "fallback_used": bool(answer.debug.get("fallback_used")),
        "retry_text": answer.debug.get("retry_text") or "",
        "repair": answer.debug.get("repair") or "none",
        "removed_sentences": list(answer.debug.get("removed_sentences") or []),
        "model_calls": int(answer.debug.get("model_calls") or 0),
        "draft_text": (answer.debug.get("verification") or {}).get("original_text")
        or answer.text,
        "timings": answer.debug.get("timings") or {},
    }


def repair_summary(label: str, turns: list[dict[str, Any]]) -> str:
    """One line: turns, prunes, retries, fallbacks, calls, and time."""
    count = len(turns)
    prunes = sum(1 for turn in turns if turn.get("repair") == "prune")
    retries = sum(1 for turn in turns if turn.get("repair") == "retry")
    fallbacks = sum(1 for turn in turns if turn.get("repair") == "fallback")
    calls = [int(turn.get("model_calls") or 0) for turn in turns]
    times = [
        float(total)
        for turn in turns
        if isinstance((turn.get("timings") or {}).get("total"), (int, float))
        for total in [(turn.get("timings") or {})["total"]]
    ]
    mean_calls = sum(calls) / count if count else 0.0
    mean_time = sum(times) / len(times) if times else 0.0
    max_time = max(times) if times else 0.0
    return (
        f"[summary] {label}: turns={count} prunes={prunes} retries={retries} "
        f"fallbacks={fallbacks} model_calls_per_turn={mean_calls:.2f} "
        f"mean_s={mean_time:.2f} max_s={max_time:.2f}"
    )


def envelope(settings: Settings, system_prompt: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    sources = ",".join(sorted(settings.retrieval_sources)) or "none"
    return {
        "created_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "model": settings.llm_model,
        "prompt_hash": prompt_hash(system_prompt),
        "git_commit": git_commit(),
        "settings": settings.masked_dict(),
        "temperature": settings.llm_temperature,
        "retrieval_sources": sources,
        "qa_mode": settings.qa_mode,
        "qa_embed_mode": settings.qa_embed_mode,
        "voice_samples": settings.voice_samples,
        "cases": cases,
    }


def build_run_settings(
    *,
    sources: str | None = None,
    qa_mode: str | None = None,
    temperature: float | None = None,
    voice_samples: str | None = None,
    retrieval_k: int | None = None,
    query_turns: int | None = None,
    query_mode: str | None = None,
    facts_in_prompt: str | None = None,
    ignore_min_score: bool = False,
    base: Settings | None = None,
) -> Settings:
    """Settings from config.py plus the explicit overrides for this run."""
    settings = base if base is not None else load_settings()
    changes: dict[str, Any] = {}
    if sources is not None:
        from src.config import _sources

        changes["retrieval_sources"] = _sources({"RETRIEVAL_SOURCES": sources})
    if qa_mode is not None:
        changes["qa_mode"] = qa_mode
    if temperature is not None:
        changes["llm_temperature"] = temperature
    if voice_samples is not None:
        changes["voice_samples"] = voice_samples
    if retrieval_k is not None:
        changes["retrieval_k"] = retrieval_k
    if query_turns is not None:
        changes["retrieval_query_turns"] = query_turns
    if query_mode is not None:
        changes["retrieval_query_mode"] = query_mode
    if facts_in_prompt is not None:
        changes["facts_in_prompt"] = facts_in_prompt
    if ignore_min_score:
        changes["retrieval_min_score"] = None
    if changes:
        settings = settings.with_overrides(**changes)
    return settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regression and conversation evals")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--query-turns", type=int, default=None)
    parser.add_argument("--query-mode", default=None, choices=["auto", "turns"])
    parser.add_argument("--facts-in-prompt", default=None, choices=["full", "summary"])
    parser.add_argument("--sources", default=None)
    parser.add_argument("--qa-mode", default=None, choices=["retrieve", "stuff"])
    parser.add_argument("--tag", default="")
    args = parser.parse_args(argv)
    settings = build_run_settings(
        sources=args.sources,
        qa_mode=args.qa_mode,
        temperature=args.temperature,
        retrieval_k=args.k,
        query_turns=args.query_turns,
        query_mode=args.query_mode,
        facts_in_prompt=args.facts_in_prompt,
    )
    system = load_system_prompt(
        stale_years=settings.source_stale_years,
        voice_samples=settings.voice_samples == "on",
        include_blog="blog" in settings.retrieval_sources,
        facts_in_prompt=settings.facts_in_prompt,
        bot_name=settings.bot_name,
        human_name=settings.human_name,
    )
    ngrams = load_rule_ngrams(
        human_name=settings.human_name, bot_name=settings.bot_name
    )
    regression = run_regression(load_cases(REGRESSION_PATH), settings, ngrams=ngrams)
    conversations = run_conversations(
        load_cases(CONVERSATION_PATH), settings, ngrams=ngrams
    )
    for row in regression:
        mark = "PASS" if row["flags_ok"] else "FAIL"
        print(f"[{mark}] {row['id']}: {row['reply'][:160]}")
    for script in conversations:
        mark = "PASS" if script["flags_ok"] else "FAIL"
        print(f"[{mark}] {script['id']}")
    conversation_turns = [turn for script in conversations for turn in script["turns"]]
    print(repair_summary("regression", regression))
    print(repair_summary("conversations", conversation_turns))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = f"_{args.tag}" if args.tag else ""
    payload = envelope(settings, system, regression)
    payload["conversations"] = conversations
    hard = sum(1 for row in regression if not row["flags_ok"])
    hard += sum(1 for row in conversations if not row["flags_ok"])
    payload["flagged_count"] = hard
    payload["repair_summary"] = {
        "regression": repair_summary("regression", regression),
        "conversations": repair_summary("conversations", conversation_turns),
    }
    out = RESULTS_DIR / f"regression{tag}_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {out} ({hard} failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
