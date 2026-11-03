"""Compare guardrail result JSON files across ablation conditions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def label_for(result: dict[str, Any], path: Path) -> str:
    sources = result.get("retrieval_sources", "?")
    mode = result.get("qa_mode", "retrieve")
    voice = result.get("voice_samples", "?")
    return f"{path.stem}|src={sources}|qa={mode}|voice={voice}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare guardrail eval runs")
    parser.add_argument(
        "results",
        nargs="+",
        type=Path,
        help="guardrail_*.json result files",
    )
    args = parser.parse_args(argv)
    runs = [(p, load_result(p)) for p in args.results]
    labels = [label_for(r, p) for p, r in runs]

    # Union of case ids in order of the first file, then extras.
    case_ids: list[str] = []
    seen: set[str] = set()
    for _, result in runs:
        for row in result.get("cases", []):
            cid = row["id"]
            if cid not in seen:
                seen.add(cid)
                case_ids.append(cid)

    by_run: list[dict[str, dict[str, Any]]] = []
    for _, result in runs:
        by_run.append({row["id"]: row for row in result.get("cases", [])})

    # Header
    print("case\t" + "\t".join(labels))
    for cid in case_ids:
        cells = [cid]
        answers: list[str] = []
        for mapping in by_run:
            row = mapping.get(cid)
            if not row:
                cells.append("MISSING")
                answers.append("")
                continue
            reply = row.get("reply") or ""
            flagged = row.get("flagged") or []
            flag_names = (
                ",".join(f.get("check", "?") for f in flagged if not f.get("ok", True))
                or "-"
            )
            cells.append(f"len={len(reply)} flags={flag_names}")
            answers.append(reply.strip())
        # Differ? compare all non-empty answers
        nonempty = [a for a in answers if a]
        differ = len(set(nonempty)) > 1 if len(nonempty) > 1 else False
        cells.append("DIFF" if differ else "same")
        print("\t".join(cells))

    print()
    print("Legend: last column is whether answers differ across runs.")
    for p, r in runs:
        print(
            f"- {p.name}: sources={r.get('retrieval_sources')} "
            f"qa_mode={r.get('qa_mode')} qa_embed_mode={r.get('qa_embed_mode')} "
            f"model={r.get('model')} flagged={r.get('flagged_count')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
