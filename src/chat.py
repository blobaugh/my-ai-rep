"""BenBot command-line chat. All answers go through answer_turn."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from src.config import Settings, configure_logging, format_settings, load_settings
from src.health import run_health_checks
from src.pipeline import Answer, answer_turn, append_turn

BANNER = "Hi, I'm BenBot, an AI that speaks for Ben. Ask me anything about him."
HELP = """/reset  Clear this conversation and show the greeting again.
/quit   Exit.
/help   Show these commands."""


def format_debug(answer: Answer) -> str:
    retrieved = answer.debug.get("retrieved") or []
    lines = []
    if answer.debug.get("guard_pattern"):
        lines.append(f"[debug] guard: {answer.debug['guard_pattern']}")
    lines.append(f"[debug] query_used: {answer.debug.get('query_used', '')!r}")
    if answer.debug.get("zero_retrieved"):
        lines.append("[debug] WARNING zero entries were retrieved")
    lines.append("[debug] retrieval:")
    if not retrieved:
        lines.append("[debug] (none)")
    for item in retrieved:
        sent = "true" if item.get("sent") else "false"
        phrasing = item.get("phrasing") or ""
        kind = item.get("kind") or ""
        extra = f" kind={kind} phrasing={phrasing!r}" if phrasing or kind else ""
        lines.append(
            f"[debug] {item.get('id')} {float(item.get('score', 0)):.4f} {sent}{extra}"
        )
    lines.append(
        f"[debug] prompt_token_estimate: {answer.debug.get('prompt_token_estimate')}"
    )
    lines.append(f"[debug] usage: {answer.debug.get('usage')}")
    lines.append(f"[debug] finish_reason: {answer.finish_reason}")
    timings = answer.debug.get("timings") or {}
    lines.append(
        "[debug] timings: "
        f"embed={timings.get('embed', 0):.3f} "
        f"search={timings.get('search', 0):.3f} "
        f"first_token={timings.get('first_token', 0):.3f} "
        f"total={timings.get('total', 0):.3f}"
    )
    lines.append(f"[debug] settings_hash: {answer.debug.get('settings_hash')}")
    lines.append(f"[debug] prompt_hash: {answer.debug.get('prompt_hash')}")
    lines.append(f"[debug] repair: {answer.debug.get('repair', 'none')}")
    for sentence in answer.debug.get("removed_sentences") or []:
        lines.append(f"[debug] removed sentence: {sentence}")
    verification = answer.debug.get("verification")
    if verification:
        lines.append(f"[debug] verification: ok={verification.get('ok')}")
        for sentence in verification.get("first_flagged_sentences") or []:
            lines.append(f"[debug] first flagged sentence: {sentence}")
        for sentence in verification.get("flagged_sentences") or []:
            lines.append(f"[debug] flagged sentence: {sentence}")
        lines.append(f"[debug] retry_used: {answer.debug.get('retry_used')}")
        lines.append(f"[debug] fallback_used: {answer.debug.get('fallback_used')}")
    if answer.debug.get("error"):
        lines.append(f"[debug] error: {answer.debug.get('error')}")
    if answer.debug.get("budget_actions"):
        lines.append(f"[debug] budget_actions: {answer.debug.get('budget_actions')}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BenBot chat")
    parser.add_argument("--ask", default=None, help="Answer one question and exit")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print retrieval, token estimate, usage, and finish reason",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream tokens as they arrive and skip verification (debugging)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.ask is not None and not args.ask.strip():
        print("Ask me something about Ben.")
        return 2

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    configure_logging(settings)
    if args.ask is None or args.debug:
        print(format_settings(settings))
    report = run_health_checks(settings)
    for warning in report.warnings:
        print(warning)
    if report.errors:
        for error in report.errors:
            print(error)
        return 1
    if args.ask is not None:
        return _ask(args.ask, settings, debug=args.debug, stream=args.stream)
    print(BANNER)
    print(report.ready_line)
    return _loop(settings, debug=args.debug, stream=args.stream)


def _ask(question: str, settings: Settings, *, debug: bool, stream: bool) -> int:
    printed: list[str] = []

    def on_delta(piece: str) -> None:
        printed.append(piece)
        print(piece, end="", flush=True)

    answer = answer_turn(
        question, [], settings, on_delta=on_delta if stream else None
    )
    if stream and printed:
        print()
    elif answer.text:
        print(answer.text)
    if answer.sources_block:
        print()
        print(answer.sources_block)
    if debug:
        print(format_debug(answer))
    return 0


def _loop(settings: Settings, *, debug: bool, stream: bool) -> int:
    history: list[dict[str, str]] = []
    while True:
        try:
            user_input = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        command = user_input.strip().lower()
        if command == "/quit":
            return 0
        if command == "/help":
            print(HELP)
            continue
        if command == "/reset":
            history = []
            print(BANNER)
            continue
        if not user_input.strip() and len(user_input) <= 2000:
            continue

        def on_delta(piece: str) -> None:
            print(piece, end="", flush=True)

        print("Bot: ", end="", flush=True)
        answer = answer_turn(
            user_input,
            history,
            settings,
            on_delta=on_delta if stream else None,
        )
        if stream and answer.debug.get("streamed"):
            print(flush=True)
        else:
            print(answer.text, flush=True)
        if answer.sources_block:
            print()
            print(answer.sources_block)
        if debug:
            print(format_debug(answer))
        if answer.finish_reason != "invalid":
            history = append_turn(
                history, user_input.strip(), answer.text, settings.history_turns
            )
    return 0


# Re-exported so older tests and evals can import them from src.chat.
__all__ = [
    "BANNER",
    "answer_turn",
    "append_turn",
    "load_settings",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
