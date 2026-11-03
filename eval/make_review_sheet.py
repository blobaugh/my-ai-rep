"""Build a markdown review sheet from one or more guardrail result files."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def load_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def condition_label(result: dict[str, Any], path: Path) -> str:
    return (
        f"{result.get('qa_mode', '?')} | voice={result.get('voice_samples', '?')} | "
        f"T={result.get('temperature', '?')} | "
        f"src={result.get('retrieval_sources', '?')} | {path.name}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make a human review sheet")
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/eval/review_sheet.md"),
        help="Output markdown path",
    )
    args = parser.parse_args(argv)

    runs = [(p, load_result(p)) for p in args.results]
    # Stable question order from first file.
    case_ids: list[str] = []
    questions: dict[str, str] = {}
    seen: set[str] = set()
    for _, result in runs:
        for row in result.get("cases", []):
            cid = row["id"]
            if cid not in seen:
                seen.add(cid)
                case_ids.append(cid)
                questions[cid] = row.get("question", "")

    lines: list[str] = [
        "# BenBot guardrail review sheet",
        "",
        "Blank **Notes** lines are for human judgment of tone and faithfulness.",
        "",
    ]

    for cid in case_ids:
        lines.append(f"## {cid}")
        lines.append("")
        lines.append(f"**Question:** {questions.get(cid, '')}")
        lines.append("")
        for path, result in runs:
            label = condition_label(result, path)
            by_id = {row["id"]: row for row in result.get("cases", [])}
            row = by_id.get(cid)
            lines.append(f"### {label}")
            lines.append("")
            if not row:
                lines.append("_missing from this result file_")
                lines.append("")
                continue
            lines.append(
                f"- flag_pass_rate: {row.get('flag_pass_rate', 'n/a')}  "
                f"distinct_answers: {row.get('distinct_answers', 'n/a')}  "
                f"faith_flags_mean: {row.get('faithfulness_flag_count_mean', 'n/a')}  "
                f"recitation_mean: {row.get('recitation_mean', 'n/a')}"
            )
            lines.append("")
            repeats = row.get("runs") or [
                {
                    "reply": row.get("reply", ""),
                    "flagged": row.get("flagged", []),
                    "faithfulness_unsupported": [],
                    "recitation": None,
                }
            ]
            for i, run in enumerate(repeats, start=1):
                lines.append(f"**Repeat {i}**")
                lines.append("")
                lines.append(run.get("reply") or "")
                lines.append("")
                flagged = run.get("flagged") or []
                faith = run.get("faithfulness_unsupported") or []
                lines.append(
                    f"_Flags:_ {flagged or 'none'}  "
                    f"_Faith:_ {faith or 'none'}  "
                    f"_Recitation:_ {run.get('recitation')}"
                )
                lines.append("")
            lines.append("**Notes:**")
            lines.append("")
            lines.append("")

    # Brief aggregate appendix for convenience.
    lines.append("## Recitation summary by file")
    lines.append("")
    for path, result in runs:
        vals: list[float] = []
        for row in result.get("cases", []):
            for run in row.get("runs") or []:
                if run.get("recitation") is not None:
                    vals.append(float(run["recitation"]))
            if not row.get("runs") and row.get("recitation_mean") is not None:
                vals.append(float(row["recitation_mean"]))
        if not vals:
            lines.append(f"- {path.name}: no scores")
            continue
        lines.append(
            f"- {path.name}: min={min(vals):.3f} "
            f"median={statistics.median(vals):.3f} max={max(vals):.3f}"
        )
    lines.append("")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
